"""RSSCollector 회귀 테스트 — 일시 오류 재시도 · 조용한 실패(0건) 경보 · 피드 단위 격리.

배경(노션 todo 02):
- (재시도) `_fetch_feed`가 일시 네트워크 오류(TransportError)를 with_retry로 한 번 더
  시도해 흡수하는지. 24h 윈도우라 한 사이클 누락은 일부 영구 손실이 될 수 있다.
- (조용한 실패) HTTP 200인데 기사가 0건인 경우(피드 포맷 변경·폐쇄)는 failed_feeds로
  안 잡히므로 별도 경보로 끌어올리는지.
- (격리) 재시도까지 소진된 피드만 failed_feeds로 격리되고 전체 수집은 멈추지 않는지.

검증 방식: RSSCollector가 만드는 httpx.AsyncClient에 MockTransport를 끼워 네트워크만
가로챈다(test_article_fetcher와 동일 패턴).
"""

import logging
from datetime import datetime

import httpx
import pytest

from services.collector import rss_collector
from services.collector.rss_collector import RSSCollector
from services.collector.rss_feeds import FeedSource

FEED = FeedSource("https://feed.example.com/rss", "example_feed", "예시언론")

RSS_WITH_ITEM = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>예시</title>
<item><title>뉴스 제목</title><link>https://news.example.com/1</link></item>
</channel></rss>"""

RSS_EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>예시</title></channel></rss>"""


@pytest.fixture
def install_transport(monkeypatch):
    """RSSCollector가 만드는 httpx.AsyncClient에 MockTransport를 끼운다."""

    def install(handler):
        real_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(rss_collector.httpx, "AsyncClient", factory)

    return install


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    """with_retry 백오프 대기를 제거해 재시도 테스트를 즉시 끝낸다."""

    async def _instant(_seconds):
        return None

    monkeypatch.setattr("services.collector.tools.with_retry.asyncio.sleep", _instant)


async def test_collects_entries(install_transport):
    install_transport(lambda request: httpx.Response(200, text=RSS_WITH_ITEM))

    collected, failed = await RSSCollector(feeds=[FEED]).collect()

    assert failed == []
    assert [c.title for c in collected] == ["뉴스 제목"]


async def test_empty_feed_warns_and_is_not_failed(install_transport, caplog):
    """HTTP 200 + 0건은 failed_feeds가 아니라 '조용한 실패' 경보로 끌어올린다."""
    install_transport(lambda request: httpx.Response(200, text=RSS_EMPTY))

    with caplog.at_level(logging.WARNING):
        collected, failed = await RSSCollector(feeds=[FEED]).collect()

    assert collected == []
    assert failed == []  # fetch 자체는 성공 → 실패 피드 아님
    assert any("0건" in record.message for record in caplog.records)


async def test_transient_error_is_retried(install_transport):
    """첫 요청이 일시 네트워크 오류(TransportError)면 재시도해 수집을 회복한다."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("일시 연결 실패")
        return httpx.Response(200, text=RSS_WITH_ITEM)

    install_transport(handler)

    collected, failed = await RSSCollector(feeds=[FEED]).collect()

    assert calls["n"] == 2  # 1차 실패 → 2차 성공
    assert failed == []
    assert len(collected) == 1


async def test_persistent_error_isolated_to_failed_feeds(install_transport):
    """재시도 소진(지속 오류) 시 그 피드만 failed_feeds로 격리되고 전체는 멈추지 않는다."""

    def handler(request):
        raise httpx.ConnectError("지속 연결 실패")

    install_transport(handler)

    collected, failed = await RSSCollector(feeds=[FEED]).collect()

    assert collected == []
    assert failed == ["example_feed"]


def test_parse_published_domestic_naive_is_kst():
    """오프셋 없는 국내 피드(einfomax 형식) 시각은 KST로 해석 — 9h 드리프트 없음."""
    dt = RSSCollector._parse_published({"published": "2026-06-17 10:40:00"}, FEED)

    assert dt == datetime(2026, 6, 17, 10, 40, 0)


def test_parse_published_investing_naive_is_utc():
    """오프셋 없는 investing 피드(tz=UTC) 시각은 UTC로 해석 → KST로 +9h."""
    investing = FeedSource(
        "https://kr.investing.com/rss/x", "investing_x", "investing.com", tz="UTC"
    )

    dt = RSSCollector._parse_published({"published": "2026-06-17 01:47:42"}, investing)

    assert dt == datetime(2026, 6, 17, 10, 47, 42)


def test_parse_published_explicit_offset_respected():
    """명시 오프셋(+0900)은 feed.tz와 무관하게 그대로 KST로 변환한다."""
    dt = RSSCollector._parse_published(
        {"published": "Wed, 17 Jun 2026 11:00:00 +0900"}, FEED
    )

    assert dt == datetime(2026, 6, 17, 11, 0, 0)
