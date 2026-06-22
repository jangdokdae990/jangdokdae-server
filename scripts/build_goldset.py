"""Bake-off 골드셋 추출 — DB 누적분의 연속 윈도우에서 골드셋 후보를 뽑아 본문을 캐시한다.

설계: docs/evaluation/01-bakeoff-design.md §2. 운영 "본문 미저장" 원칙의 명시적 예외 —
정제 본문은 오프라인 실험 픽스처(골드셋 JSON)에만 캐시하고 운영 DB엔 저장하지 않는다.

출력 JSON의 gold_cluster는 null(미라벨) 상태로 둔다 — LLM 1차 제안 + 사람 스팟 검수로 채운다.

표준 실행(앱 venv): python -m scripts.build_goldset --start 2026-06-16 --end 2026-06-18
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

import httpx
from sqlalchemy import text

from app.db.base import engine
from services.analyzer.article_fetcher import fetch_article_body
from services.preprocessor.body_processor import clean_body

logger = logging.getLogger(__name__)

OUT_DIR = Path("scripts/data")
# 본문 fetch 동시성 — 수집기 RSS 폴링과 동일한 보수적 상한(매체 부하·차단 회피).
FETCH_CONCURRENCY = 5
# 현재 코퍼스는 100% 한국어다 — investing.com 피드도 실제로는 kr.investing.com(한국어
# 현지화판)이라 영어 기사가 없다. 영어 소스가 실제로 추가되면 이 함수에 판별 규칙을 넣는다.
def _lang(news_source: str) -> str:  # noqa: ARG001 — 향후 영어 소스 추가 대비 시그니처 유지
    return "ko"


async def _load_window(start: datetime, end: datetime) -> list[dict]:
    """[start, end) 발행 윈도우에서 분석 대상(is_filtered=false) 뉴스를 전수 로드한다."""
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT id, title, url, news_source, rss_source, published_at
                    FROM news
                    WHERE is_filtered = false
                      AND published_at >= :start AND published_at < :end
                    ORDER BY published_at
                    """
                ),
                {"start": start, "end": end},
            )
        ).all()
    return [dict(r._mapping) for r in rows]


async def _fetch_body(
    client: httpx.AsyncClient, sem: asyncio.Semaphore, item: dict
) -> tuple[str | None, bool]:
    """단일 기사 본문을 fetch·정제한다. 실패·페이월·과소 추출은 (None, False).

    수백 건의 외부 URL을 다루므로 한 건의 예외(SSL 핸드셰이크 실패 등 httpx가 감싸지 못한
    저수준 오류 포함)가 배치 전체를 중단시키지 않도록 건별로 격리한다 — 골드셋은 실험
    픽스처라 일부 본문 누락은 body_ok=False로 표시하고 진행하면 된다.
    """
    try:
        async with sem:
            raw = await fetch_article_body(item["url"], client=client)
    except Exception as exc:  # noqa: BLE001 — 건별 격리(이유는 docstring)
        logger.warning("본문 fetch 예외 url=%s err=%r", item["url"], exc)
        return None, False
    if not raw:
        return None, False
    return clean_body(raw), True


async def build(start: datetime, end: datetime, out_path: Path) -> None:
    records = await _load_window(start, end)
    logger.info("윈도우 로드 %s~%s → %d건", start.date(), end.date(), len(records))

    sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    async with httpx.AsyncClient(
        timeout=10.0, headers={"User-Agent": "jangdokdae-goldset/1.0"}, follow_redirects=True
    ) as client:
        bodies = await asyncio.gather(
            *(_fetch_body(client, sem, r) for r in records)
        )

    items = []
    body_ok = 0
    for rec, (body, ok) in zip(records, bodies, strict=True):
        body_ok += ok
        items.append(
            {
                "id": rec["id"],
                "title": rec["title"],
                "url": rec["url"],
                "news_source": rec["news_source"],
                "lang": _lang(rec["news_source"]),
                "published_at": rec["published_at"].isoformat() if rec["published_at"] else None,
                "body": body,
                "body_ok": ok,
                "gold_cluster": None,  # LLM 제안 + 사람 검수로 채움
                "tags": [],
            }
        )

    n_en = sum(1 for it in items if it["lang"] == "en")
    payload = {
        "meta": {
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "count": len(items),
            "lang_en": n_en,
            "lang_ko": len(items) - n_en,
            "body_ok": body_ok,
            "body_failed": len(items) - body_ok,
        },
        "items": items,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "골드셋 저장 %s — %d건(en=%d) 본문 ok=%d/%d",
        out_path, len(items), n_en, body_ok, len(items),
    )
    await engine.dispose()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Bake-off 골드셋 추출")
    p.add_argument("--start", required=True, help="윈도우 시작 (YYYY-MM-DD, 포함)")
    p.add_argument("--end", required=True, help="윈도우 끝 (YYYY-MM-DD, 미포함)")
    p.add_argument("--out", default=None, help="출력 경로 (기본 scripts/data/goldset_<start>.json)")
    return p.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _parse_args()
    start = datetime.fromisoformat(args.start)
    end = datetime.fromisoformat(args.end)
    out = Path(args.out) if args.out else OUT_DIR / f"goldset_{args.start}.json"
    asyncio.run(build(start, end, out))


if __name__ == "__main__":
    main()
