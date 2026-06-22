"""분석 단계 단독 실행 — DB 클러스터 → 콘텐츠 생성 → DB 저장(로컬 E2E 테스트).

전체 파이프라인([services.pipeline.runner])과 달리 분석 단계만 떼어 돌린다. run()의
get_unanalyzed_clusters는 "오늘(KST)" 클러스터만 보지만, 이 러너는 run_date 무관하게 미분석
클러스터(또는 특정 cluster-id)를 받아 NewsAnalyzer.analyze_cluster로 분류·생성·적재하고,
검증용으로 생성 결과(title·태그·백필 id·heads 요약)를 출력한다.

사용:
    python -m scripts.run_analysis                          # 최신 미분석 클러스터 1건
    python -m scripts.run_analysis --limit 3                # 최신 미분석 3건
    python -m scripts.run_analysis --cluster-id 42          # 특정 클러스터
    python -m scripts.run_analysis --cluster-id 42 --rerun  # 기존 결과 삭제 후 재분석
    python -m scripts.run_analysis --min-size 1 --limit 0 --rerun  # 분석된 전체 재분석
"""

import argparse
import asyncio
import logging

from sqlalchemy import select

from app.config import settings
from app.db.base import AsyncSessionLocal
from app.db.orm_models.issue_docent import IssueDocent
from app.db.orm_models.news_analysis import NewsAnalysis
from app.db.orm_models.news_cluster import NewsCluster
from app.db.queries import (
    delete_analysis_for_cluster,
    get_analyzed_clusters,
    get_cluster_by_id,
    get_latest_unanalyzed_clusters,
)
from services.pipeline.news_analyzer import NewsAnalyzer

logger = logging.getLogger(__name__)


async def _has_analysis(db, cluster_id: int) -> bool:
    """해당 클러스터에 이미 분석 결과가 있는지(중복 분석·덮어쓰기 판단용)."""
    result = await db.execute(
        select(NewsAnalysis.id).where(NewsAnalysis.cluster_id == cluster_id)
    )
    return result.scalars().first() is not None


async def _print_result(db, cluster_id: int) -> None:
    """적재된 news_analysis·issue_docent를 읽어 생성 결과를 사람이 보기 좋게 출력."""
    analysis = (
        await db.execute(select(NewsAnalysis).where(NewsAnalysis.cluster_id == cluster_id))
    ).scalars().first()
    docent = (
        await db.execute(select(IssueDocent).where(IssueDocent.cluster_id == cluster_id))
    ).scalars().first()
    if analysis is None:
        print(f"  (cluster {cluster_id}: 저장된 결과 없음 — 분석이 스킵/실패했을 수 있음)")
        return
    companies = [t.get("name") for t in analysis.company_tags]
    title = docent.title if docent is not None else "(비투자성 — 콘텐츠 생략)"
    print(f"  title       : {title}")
    print(
        f"  scope/frame : {analysis.scope} / {analysis.frame} "
        f"({analysis.direction}, conf={analysis.confidence})"
    )
    print(f"  relevant    : {analysis.is_investment_relevant}")
    print(f"  company     : tags={companies} → ids={analysis.company_ids}")
    print(f"  sector      : tags={analysis.sector_tags} → ids={analysis.sector_ids}")
    print(f"  needs_review: {analysis.needs_review}")
    # relevance 필터로 걸러진 경우 issue_docent가 없다(분류만 적재).
    if docent is None:
        print("  (relevance 필터: 비투자성 뉴스 — issue_docent 미적재)")
        return
    for h in docent.content_heads:
        answer = (h.get("answer") or "").replace("\n", " ")
        print(f"  · [{h.get('label')}] {h.get('question')} → {answer[:80]}")


async def _analyze_one(analyzer: NewsAnalyzer, cluster: NewsCluster, rerun: bool) -> str:
    """클러스터 1건을 **독립 세션**으로 분석. 'done'|'skip'|'fail' 반환.

    배치 견고성 — 세션을 건마다 새로 열어, 한 건의 실패가 연결을 오염시켜 다음 건을 멈추지
    않게 격리한다. rollback 자체가 실패해도(드문 async/pre_ping 충돌) 삼켜서 배치는 계속된다.
    """
    print(f"\n=== cluster {cluster.id} (run_date={cluster.run_date}, size={cluster.size}) ===")
    async with AsyncSessionLocal() as db:
        try:
            if rerun:
                await delete_analysis_for_cluster(db, cluster.id, cluster.member_news_ids)
                await db.commit()
            elif await _has_analysis(db, cluster.id):
                # 삭제 없이 재분석하면 save가 ON CONFLICT DO NOTHING으로 무시돼 옛 결과만 보인다.
                print("  [스킵] 이미 분석됨 — 덮어쓰려면 --rerun")
                await _print_result(db, cluster.id)
                return "skip"
            outcome = await analyzer.analyze_cluster(db, cluster)
            tag = " [비투자성 skip]" if outcome.skipped_irrelevant else ""
            print(f"  [완료] needs_review={outcome.review}{tag}")
            await _print_result(db, cluster.id)
            return "done"
        except Exception as exc:  # noqa: BLE001 — 한 클러스터 실패가 전체를 멈추지 않게 격리
            try:
                await db.rollback()
            except Exception:  # noqa: BLE001 — rollback 실패(연결 오염)도 배치 진행에 영향 없게
                pass
            logger.exception("cluster %s 분석 실패", cluster.id)
            print(f"  [실패] {exc}")
            return "fail"


async def run_analysis(
    *, cluster_id: int | None = None, limit: int = 1, min_size: int = 1, rerun: bool = False
) -> None:
    analyzer = NewsAnalyzer()
    # 대상 목록은 별도 세션 1회로 조회(객체는 detached로 읽기만 — 처리 자체는 건마다 새 세션).
    async with AsyncSessionLocal() as db:
        if cluster_id is not None:
            cluster = await get_cluster_by_id(db, cluster_id)
            clusters = [cluster] if cluster is not None else []
        elif rerun:
            # 배치 --rerun: 이미 분석된 클러스터를 대상으로 재분석(개선 분류 반영 등).
            clusters = await get_analyzed_clusters(db, limit, min_size)
        else:
            clusters = await get_latest_unanalyzed_clusters(db, limit, min_size)
    if not clusters:
        print("대상 클러스터 없음 (--cluster-id / --min-size / --rerun 확인)")
        return

    print(f"대상 클러스터 {len(clusters)}건: {[c.id for c in clusters]}")
    counts = {"done": 0, "skip": 0, "fail": 0}
    for i, cluster in enumerate(clusters):
        counts[await _analyze_one(analyzer, cluster, rerun)] += 1
        # 이슈 간 호출 간격(Vertex rate limit 완화) — 마지막 건 뒤에는 생략.
        if settings.llm_request_delay_seconds > 0 and i < len(clusters) - 1:
            await asyncio.sleep(settings.llm_request_delay_seconds)
    print(
        f"\n=== 요약: 완료 {counts['done']} / 스킵 {counts['skip']} / 실패 {counts['fail']} "
        f"(총 {len(clusters)}) ==="
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    parser = argparse.ArgumentParser(
        description="분석 단계 단독 실행 (DB 클러스터 → 콘텐츠 생성 → DB 저장)"
    )
    parser.add_argument("--cluster-id", type=int, default=None, help="특정 클러스터만 분석")
    parser.add_argument("--limit", type=int, default=1, help="최신 미분석 N건 (0=무제한, 기본 1)")
    parser.add_argument("--min-size", type=int, default=1, help="이 크기 이상 클러스터만 (기본 1)")
    parser.add_argument(
        "--rerun", action="store_true",
        help="기존 결과 삭제 후 재분석. 배치(--cluster-id 없이)면 이미 분석된 클러스터가 대상.",
    )
    args = parser.parse_args()
    asyncio.run(
        run_analysis(
            cluster_id=args.cluster_id, limit=args.limit,
            min_size=args.min_size, rerun=args.rerun,
        )
    )
