# 단독 실행: uv run pytest tests/test_rss_feeds.py -s
"""RSS 피드 레지스트리 로더 테스트 (설계 02 §4).

피드 정본을 코드 상수에서 YAML로 이관함 — 로더가 YAML을 FeedSource로 정확히 파싱하고
active=false를 제외하며, 필수 키 누락 시 즉시 실패하는지 검증한다. 정본 config/news_feeds.yaml도
로드 가능한지 함께 본다(잘못된 레지스트리가 조용히 빈 목록이 되면 수집량 급감을 놓친다).
"""

from pathlib import Path

import pytest

from services.collector.rss_feeds import ALL_FEEDS, FeedSource, load_feeds


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "feeds.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_loads_feeds_with_defaults(tmp_path):
    path = _write(tmp_path, """
feeds:
  - { rss_source: a_feed, publisher: 가언론, url: "https://a.com/rss" }
""")
    feeds = load_feeds(path)
    assert feeds == [FeedSource(url="https://a.com/rss", rss_source="a_feed", publisher="가언론")]
    assert feeds[0].region == "korea"      # 기본값
    assert feeds[0].tz == "Asia/Seoul"     # 기본값


def test_explicit_region_and_tz_respected(tmp_path):
    path = _write(tmp_path, """
feeds:
  - { rss_source: us_feed, publisher: Foo, url: "https://f.com/rss", region: us, tz: UTC }
""")
    feed = load_feeds(path)[0]
    assert feed.region == "us"
    assert feed.tz == "UTC"


def test_inactive_feed_excluded_by_default(tmp_path):
    path = _write(tmp_path, """
feeds:
  - { rss_source: on_feed, publisher: A, url: "https://a.com/rss" }
  - { rss_source: off_feed, publisher: B, url: "https://b.com/rss", active: false }
""")
    assert [f.rss_source for f in load_feeds(path)] == ["on_feed"]
    # active_only=False면 비활성 피드도 포함(운영 점검용)
    assert len(load_feeds(path, active_only=False)) == 2


def test_missing_required_key_raises(tmp_path):
    # publisher 누락 — 잘못된 레지스트리를 조용히 건너뛰지 않고 즉시 실패한다
    path = _write(tmp_path, """
feeds:
  - { rss_source: bad_feed, url: "https://a.com/rss" }
""")
    with pytest.raises(KeyError):
        load_feeds(path)


def test_production_registry_loads_nonempty():
    # 정본 config/news_feeds.yaml이 실제로 로드되고 비어 있지 않은지(설정 회귀 가드)
    assert len(ALL_FEEDS) > 0
    assert all(f.url and f.rss_source and f.publisher for f in ALL_FEEDS)
