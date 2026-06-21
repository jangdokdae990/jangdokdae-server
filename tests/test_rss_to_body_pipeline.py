# 단독 실행: uv run pytest tests/test_rss_to_body_pipeline.py -s
"""RSS 수집 → 본문 추출 → 본문 전처리 파이프라인 라이브 점검.

실제 RSS 피드를 폴링해 기사 메타를 모으고(`RSSCollector`), 각 기사 본문을 trafilatura로
fetch(`article_fetcher`)한 뒤, 임베딩 입력용으로 정제·청크(`body_processor`)하는 전 과정을
한 번에 돌려 결과를 `tests/data/rss_body_pipeline.json`으로 떨군다 — 정제 전/후를 눈으로
비교해 보일러플레이트 제거·청크 품질을 점검하기 위함(설계 02 §8.4 · 04 Step2 · 05 §2.2).

외부 네트워크가 필요하다 — RSS 폴링이 전부 실패하거나 기사가 0건이면 skip한다.
샘플 수는 `RSS_PIPELINE_SAMPLE`(기본 10)로 조정한다.
"""

import json
import os
from pathlib import Path

import httpx
import pytest

from app.config import settings
from services.analyzer.article_fetcher import fetch_article_body
from services.collector.rss_collector import RSSCollector
from services.preprocessor.body_processor import chunk_with_overlap, clean_body
from utils.http import USER_AGENT

SAMPLE_SIZE = int(os.getenv("RSS_PIPELINE_SAMPLE", "50"))
OUTPUT_PATH = Path(__file__).parent / "data" / "rss_body_pipeline.json"


def _published_key(item):
    # 발행일 최신순 정렬용 — None은 가장 뒤로.
    return (item.published_at is not None, item.published_at)


async def test_rss_to_body_pipeline_dumps_json():
    """RSS→본문→전처리를 실제로 돌리고 결과를 tests/data/ JSON으로 출력한다."""
    # 1) RSS 수집 — 활성 피드 폴링 (OSError는 ssl.SSLError 등 저수준 네트워크 오류 포함)
    try:
        collected, failed_feeds = await RSSCollector().collect()
    except (httpx.HTTPError, OSError) as exc:
        pytest.skip(f"RSS 폴링 불가 — 네트워크 점검 필요: {exc}")

    if not collected:
        pytest.skip("RSS 수집 0건 — 네트워크/피드 상태 점검 필요")

    sample = sorted(collected, key=_published_key, reverse=True)[:SAMPLE_SIZE]

    # 2) 본문 추출 → 3) 본문 전처리 (정제 + 청크)
    articles: list[dict] = []
    async with httpx.AsyncClient(
        timeout=10.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        for item in sample:
            # 라이브 다중 사이트 fetch — 일부는 raw ssl.SSLError(OSError) 등으로 깨질 수 있어
            # 기사별로 방어해 한 건 실패가 전체 파이프라인 점검을 멈추지 않게 한다.
            fetch_error: str | None = None
            try:
                raw = await fetch_article_body(item.url, client=client)
            except (httpx.HTTPError, OSError) as exc:
                raw, fetch_error = None, f"{type(exc).__name__}: {exc}"
            cleaned = clean_body(raw) if raw else ""
            chunks = (
                chunk_with_overlap(cleaned, settings.chunk_size, settings.chunk_overlap)
                if cleaned
                else []
            )
            articles.append({
                "rss_source": item.rss_source,
                "news_source": item.news_source,
                "title": item.title,
                "url": item.url,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "fetch_ok": raw is not None,
                "fetch_error": fetch_error,
                "raw_len": len(raw or ""),
                "cleaned_len": len(cleaned),
                "chunk_count": len(chunks),
                "body_raw": raw,
                "body_cleaned": cleaned,
                "chunks": chunks,
            })

    success = sum(1 for a in articles if a["fetch_ok"])
    report = {
        "sample_size": SAMPLE_SIZE,
        "collected_total": len(collected),
        "failed_feeds": failed_feeds,
        "fetch_success": success,
        "articles": articles,
    }

    # 4) tests/data/ JSON 출력
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(
        f"\n[RSS→본문→전처리] 수집 {len(collected)}건 → 샘플 {len(sample)} → "
        f"본문 추출 성공 {success}/{len(sample)} → {OUTPUT_PATH}"
    )
    for a in articles:
        mark = "O" if a["fetch_ok"] else "X"
        print(f"  [{mark}] {a['news_source']} raw={a['raw_len']} "
              f"cleaned={a['cleaned_len']} chunks={a['chunk_count']} {a['title'][:30]}")

    # 파이프라인이 실제로 결과를 만들어 파일로 떨궜는지 검증
    assert OUTPUT_PATH.exists()
    assert success >= 1, "본문 추출이 한 건도 성공하지 못함 — fetch 경로 점검 필요"
