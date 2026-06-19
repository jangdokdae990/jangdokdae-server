"""DB 조회·갱신 쿼리 모음 — 파이프라인 단계 간 DB 접근을 한곳에 모은다.

임베딩·클러스터링 단계의 상태 핸드오프 쿼리를 둔다. 각 단계는 "미처리 레코드"만 집어가므로
부분 실패 후 재실행해도 남은 것만 처리된다(멱등).
"""

from datetime import date, datetime

from sqlalchemy import Text, any_, delete, select, type_coerce, update
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.orm_models.company_entity import CompanyEntity
from app.db.orm_models.issue_docent import IssueDocent
from app.db.orm_models.news import News
from app.db.orm_models.news_analysis import NewsAnalysis
from app.db.orm_models.news_cluster import NewsCluster
from app.db.orm_models.report_chunk import ReportChunk
from app.db.orm_models.sector import Sector
from app.db.orm_models.stock_price import StockPrice


async def get_unembedded_news(db: AsyncSession) -> list[News]:
    """임베딩 대기 뉴스 조회 — is_filtered=FALSE AND embedding IS NULL.

    탈락분·기임베딩분은 제외돼 재실행해도 새 미임베딩분만 집어간다(멱등).
    """
    result = await db.execute(
        select(News)
        .where(News.is_filtered.is_(False))
        .where(News.embedding.is_(None))
        .order_by(News.id)
    )
    return list(result.scalars().all())


async def get_unembedded_report_chunks(db: AsyncSession) -> list[ReportChunk]:
    """임베딩 대기 사업보고서 청크 조회 — embedding IS NULL."""
    result = await db.execute(
        select(ReportChunk).where(ReportChunk.embedding.is_(None)).order_by(ReportChunk.id)
    )
    return list(result.scalars().all())


async def save_news_embeddings(db: AsyncSession, id_to_vector: dict[int, list[float]]) -> int:
    """뉴스 임베딩을 id별로 일괄 저장. 저장 건수를 반환(빈 입력은 0, DB 미접근)."""
    if not id_to_vector:
        return 0
    # SQLAlchemy 2.0 ORM 일괄 UPDATE(기본키 기준) — 행마다 UPDATE 문을 모아 1회 round-trip.
    await db.execute(
        update(News),
        [{"id": news_id, "embedding": vector} for news_id, vector in id_to_vector.items()],
    )
    await db.commit()
    return len(id_to_vector)


async def save_chunk_embeddings(db: AsyncSession, id_to_vector: dict[int, list[float]]) -> int:
    """사업보고서 청크 임베딩을 id별로 일괄 저장. 저장 건수를 반환(빈 입력은 0)."""
    if not id_to_vector:
        return 0
    await db.execute(
        update(ReportChunk),
        [{"id": chunk_id, "embedding": vector} for chunk_id, vector in id_to_vector.items()],
    )
    await db.commit()
    return len(id_to_vector)


async def get_clusterable_news(db: AsyncSession, since: datetime) -> list[News]:
    """클러스터링 대상 뉴스 조회 — 당일 수집·임베딩 완료·미탈락·비중복·미분석분.

    since(KST naive)는 수집 시각 하한 — 없으면 미분석 백로그 전체가 매일 재클러스터링된다.
    근접 중복·전처리 탈락·분석 완료 행은 제외한다.
    """
    result = await db.execute(
        select(News)
        .where(News.created_at >= since)
        .where(News.is_filtered.is_(False))
        .where(News.is_duplicate.is_(False))
        .where(News.is_analyzed.is_(False))
        .where(News.embedding.is_not(None))
        .order_by(News.id)
    )
    return list(result.scalars().all())


# ── 분석 단계(NewsAnalyzer, →10) 핸드오프 ──────────────────────────────
# 분류·콘텐츠 적재는 (cluster_id) 유니크 키로 ON CONFLICT DO NOTHING — 재실행 멱등.
# 아래 save_*·mark_*는 commit하지 않는다(이슈 1건의 분류·콘텐츠·플래그를 호출부가 한 번에 commit).


async def get_unanalyzed_clusters(
    db: AsyncSession, run_date: date, limit: int
) -> list[NewsCluster]:
    """분석 대기 클러스터 — 해당 실행일자 중 아직 news_analysis가 없는 것, importance 내림차순.

    이미 분석된 클러스터(news_analysis 존재)는 제외해 재실행 시 남은 것만 처리한다(멱등).
    """
    analyzed = select(NewsAnalysis.cluster_id)
    result = await db.execute(
        select(NewsCluster)
        .where(NewsCluster.run_date == run_date)
        .where(NewsCluster.id.notin_(analyzed))
        .order_by(NewsCluster.importance.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


# ── 분석 전용 러너(scripts.run_analysis) 보조 — 날짜 무관 타겟·재실행 ──────────────
# run()의 get_unanalyzed_clusters는 "오늘(KST)" 클러스터만 보지만, 로컬 테스트는 과거 날짜
# 클러스터를 대상으로 돌려야 하므로 날짜 필터 없는 조회·특정 id 조회·재실행 삭제를 따로 둔다.


async def get_latest_unanalyzed_clusters(
    db: AsyncSession, limit: int, min_size: int = 1
) -> list[NewsCluster]:
    """미분석 클러스터를 run_date 무관하게 최신순으로 N건 — 로컬 분석 테스트용.

    run_date 필터가 없다는 점만 get_unanalyzed_clusters와 다르다(news_analysis 존재분은 제외).
    min_size 이상 크기만 대상(기본 1=전체). limit<=0이면 무제한.
    """
    analyzed = select(NewsAnalysis.cluster_id)
    stmt = (
        select(NewsCluster)
        .where(NewsCluster.id.notin_(analyzed))
        .where(NewsCluster.size >= min_size)
        .order_by(NewsCluster.run_date.desc(), NewsCluster.importance.desc())
    )
    if limit > 0:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_analyzed_clusters(
    db: AsyncSession, limit: int, min_size: int = 1
) -> list[NewsCluster]:
    """이미 분석된(news_analysis 존재) 클러스터를 최신순으로 N건 — 배치 재분석(--rerun)용.

    get_latest_unanalyzed_clusters의 역(`id IN (분석됨)`). 분류 개선 등으로 기존 적재분을 다시
    분석할 때 대상이 된다. min_size 이상만, limit<=0이면 무제한.
    """
    analyzed = select(NewsAnalysis.cluster_id)
    stmt = (
        select(NewsCluster)
        .where(NewsCluster.id.in_(analyzed))
        .where(NewsCluster.size >= min_size)
        .order_by(NewsCluster.run_date.desc(), NewsCluster.importance.desc())
    )
    if limit > 0:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_cluster_by_id(db: AsyncSession, cluster_id: int) -> NewsCluster | None:
    """특정 클러스터 1건 조회(분석 여부 무관) — 러너의 --cluster-id 타겟용. 없으면 None."""
    result = await db.execute(select(NewsCluster).where(NewsCluster.id == cluster_id))
    return result.scalars().first()


async def delete_analysis_for_cluster(
    db: AsyncSession, cluster_id: int, member_news_ids: list[int]
) -> None:
    """클러스터의 기존 분석 산출물을 지워 재분석을 허용한다(러너 --rerun).

    save_*가 ON CONFLICT DO NOTHING이라 삭제 없이는 덮어쓰기가 안 된다. news_analysis·
    issue_docent 행을 지우고 멤버 News의 is_analyzed=False로 되돌린다. 커밋은 호출부 책임.
    """
    await db.execute(delete(NewsAnalysis).where(NewsAnalysis.cluster_id == cluster_id))
    await db.execute(delete(IssueDocent).where(IssueDocent.cluster_id == cluster_id))
    if member_news_ids:
        await db.execute(
            update(News).where(News.id.in_(member_news_ids)).values(is_analyzed=False)
        )


async def get_cluster_articles(db: AsyncSession, member_news_ids: list[int]) -> list[News]:
    """클러스터 소속 기사 News 행을 member_news_ids 순서(중심 근접순)대로 반환한다."""
    if not member_news_ids:
        return []
    result = await db.execute(select(News).where(News.id.in_(member_news_ids)))
    by_id = {n.id: n for n in result.scalars().all()}
    return [by_id[i] for i in member_news_ids if i in by_id]


async def save_news_analysis(
    db: AsyncSession,
    *,
    cluster_id: int,
    scope: str,
    frame: str,
    origin: str,
    direction: str,
    confidence: float,
    sector_tags: list[str],
    company_tags: list[dict],
    company_ids: list[int],
    sector_ids: list[int],
    term_tags: list[str],
    needs_review: bool,
    is_investment_relevant: bool = True,
) -> None:
    """분류 결과를 적재(클러스터당 1행, 중복 시 무시).

    company_ids·sector_ids는 태그(이름)를 마스터(company_entities·sectors)로 해소한 백필 —
    "특정 기업/섹터를 언급한 이슈" 조회·주가 연동의 조인 키. 원문 태그는 그대로 함께 보존한다.
    is_investment_relevant=False면 비투자성 뉴스 — 분류만 남기고 issue_docent는 생략한다(호출부).
    """
    stmt = (
        pg_insert(NewsAnalysis)
        .values(
            cluster_id=cluster_id,
            scope=scope,
            frame=frame,
            origin=origin,
            direction=direction,
            confidence=confidence,
            sector_tags=sector_tags,
            company_tags=company_tags,
            company_ids=company_ids,
            sector_ids=sector_ids,
            term_tags=term_tags,
            needs_review=needs_review,
            is_investment_relevant=is_investment_relevant,
        )
        .on_conflict_do_nothing(index_elements=["cluster_id"])
    )
    await db.execute(stmt)


async def save_issue_docent(
    db: AsyncSession,
    *,
    cluster_id: int,
    title: str,
    hook_lines: dict,
    content_heads: list[dict],
    connection_module: list[dict],
    evidence_spans: list[dict],
    term_spans: list[dict],
) -> None:
    """생성 콘텐츠를 적재(클러스터당 1행, 중복 시 무시)."""
    stmt = (
        pg_insert(IssueDocent)
        .values(
            cluster_id=cluster_id,
            title=title,
            hook_lines=hook_lines,
            content_heads=content_heads,
            connection_module=connection_module,
            evidence_spans=evidence_spans,
            term_spans=term_spans,
        )
        .on_conflict_do_nothing(index_elements=["cluster_id"])
    )
    await db.execute(stmt)


async def mark_news_analyzed(db: AsyncSession, news_ids: list[int]) -> None:
    """클러스터 소속 기사를 분석 완료로 표시(is_analyzed=True). 빈 입력은 무동작."""
    if not news_ids:
        return
    await db.execute(update(News).where(News.id.in_(news_ids)).values(is_analyzed=True))


# ── OPINION 현재가 보강용 key 조회 (설계 08 §5 OPINION 몫, 10 §6) ──────────
# 분류기는 기업명만 주므로 name→stock_code(company_entities)→최신 종가(stock_prices)로 잇는다.


async def get_company_by_name(db: AsyncSession, name: str) -> CompanyEntity | None:
    """기업명으로 company_entity 조회 — name_ko 정확 일치, 없으면 aliases 폴백. 미스 시 None."""
    if not name:
        return None
    result = await db.execute(
        select(CompanyEntity)
        .where((CompanyEntity.name_ko == name) | (name == any_(CompanyEntity.aliases)))
        .limit(1)
    )
    return result.scalars().first()


# ── 태그→마스터 id 해소(백필) — news_analysis.company_ids/sector_ids 적재용 ────────
# 분류기는 기업·섹터 이름만 주므로, 관계형 조회·주가 연동을 위해 마스터 id로 해소한다.
# 미매칭 이름은 결과에서 제외하고(원문 태그는 보존) 부분 매칭을 허용한다.


async def resolve_company_ids(db: AsyncSession, names: list[str]) -> list[int]:
    """기업명 목록을 company_entities.id로 해소 — name_ko 정확 일치 OR aliases 폴백.

    get_company_by_name()과 같은 매칭 규칙을 N개 이름에 대해 1쿼리로 묶는다. 매칭된 id만
    오름차순·중복 제거해 반환(미매칭 이름은 제외). 빈 입력은 빈 리스트(DB 미접근).
    """
    wanted = [n for n in {n.strip() for n in names} if n]
    if not wanted:
        return []
    # aliases는 generic ARRAY라 .overlap()이 없음 → postgresql ARRAY로 재해석해 배열 겹침(&&).
    aliases_pg = type_coerce(CompanyEntity.aliases, PG_ARRAY(Text))
    result = await db.execute(
        select(CompanyEntity.id).where(
            CompanyEntity.name_ko.in_(wanted) | aliases_pg.overlap(wanted)
        )
    )
    return sorted({row[0] for row in result.all()})


async def resolve_sector_ids(db: AsyncSession, names: list[str]) -> list[int]:
    """섹터명 목록을 sectors.id로 해소 — sectors.name_ko 정확 일치(마스터가 단일 소스).

    매칭된 id만 오름차순·중복 제거해 반환. 마스터에 없는 섹터명은 제외(원문 sector_tags는 보존).
    빈 입력은 빈 리스트(DB 미접근).
    """
    wanted = [n for n in {n.strip() for n in names} if n]
    if not wanted:
        return []
    result = await db.execute(select(Sector.id).where(Sector.name_ko.in_(wanted)))
    return sorted({row[0] for row in result.all()})


async def get_latest_stock_price(db: AsyncSession, stock_code: str) -> StockPrice | None:
    """종목 코드의 최신 거래일 주가 1건. 데이터 없으면 None."""
    result = await db.execute(
        select(StockPrice)
        .where(StockPrice.stock_code == stock_code)
        .order_by(StockPrice.date.desc())
        .limit(1)
    )
    return result.scalars().first()
