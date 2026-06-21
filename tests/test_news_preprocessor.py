# 단독 실행: uv run pytest tests/test_news_preprocessor.py -s
"""news_preprocessor 단위 테스트 — 순수 함수 + 파이프라인 조립 (설계 04 §3·§4).

DB 접근 없는 순수 인메모리 모듈이므로 외부 의존성 없이 검증한다.
구성: [정규화] → [날짜 필터] → [제목 중복] → [run_preprocessing 조립].
"""

from datetime import datetime, timedelta

from services.preprocessor.news_preprocessor import (
    clean_title,
    deduplicate_by_title,
    is_recent,
    jaccard,
    normalize,
    remove_tracking_params,
    run_preprocessing,
    title_bigrams,
)

NOW = datetime(2026, 5, 28, 9, 0, 0)  # 테스트 기준 수집 시각 (KST naive)


def _record(title: str, url: str, published_at: datetime | None = NOW) -> dict:
    """to_record() 형식의 수집 레코드를 만든다(published_at 기본=NOW)."""
    return {
        "title": title,
        "url": url,
        "rss_source": "hankyung",
        "news_source": "한국경제",
        "published_at": published_at,
    }


# ── Step 1. HTML 정제 ───────────────────────────────────────────────────────
class TestCleanTitle:
    def test_strips_tags(self):
        assert clean_title("<b>삼성전자</b> 3분기 실적") == "삼성전자 3분기 실적"

    def test_unescapes_entities(self):
        assert clean_title("영업이익 &amp; 매출 &lt;전년") == "영업이익 & 매출 <전년"

    def test_tags_and_entities_together(self):
        assert clean_title("<b>삼성</b> 영업이익 &amp;전년") == "삼성 영업이익 &전년"

    def test_plain_text_unchanged(self):
        assert clean_title("삼성전자 신고가 경신") == "삼성전자 신고가 경신"

    def test_strips_surrounding_whitespace(self):
        assert clean_title("  코스피 상승  ") == "코스피 상승"

    def test_empty_returns_empty(self):
        assert clean_title("") == ""


# ── Step 2. URL 정규화 ──────────────────────────────────────────────────────
class TestRemoveTrackingParams:
    def test_removes_utm_and_fbclid(self):
        url = "https://hankyung.com/article/123?utm_source=naver&fbclid=abc"
        assert remove_tracking_params(url) == "https://hankyung.com/article/123"

    def test_keeps_non_tracking_params(self):
        url = "https://hankyung.com/article?id=123&utm_medium=news"
        assert remove_tracking_params(url) == "https://hankyung.com/article?id=123"

    def test_preserves_query_order(self):
        url = "https://example.com/a?b=2&a=1&utm_term=x"
        assert remove_tracking_params(url) == "https://example.com/a?b=2&a=1"

    def test_no_query_unchanged(self):
        url = "https://hankyung.com/article/123"
        assert remove_tracking_params(url) == url

    def test_empty_returns_empty(self):
        assert remove_tracking_params("") == ""

    def test_normalized_urls_collapse_to_same(self):
        # 다른 트래킹 파라미터가 붙어도 정규화 후 동일 URL → ON CONFLICT(url)이 차단
        base = "https://hankyung.com/article/123"
        a = remove_tracking_params(f"{base}?utm_source=naver&utm_medium=news")
        b = remove_tracking_params(f"{base}?fbclid=abc123")
        assert a == b == base


class TestNormalize:
    def test_returns_clean_title_and_url(self):
        title, url = normalize("<b>제목</b>", "https://x.com/a?utm_source=n")
        assert title == "제목"
        assert url == "https://x.com/a"


# ── Step 3. 날짜 필터 ───────────────────────────────────────────────────────
class TestIsRecent:
    def test_within_threshold(self):
        assert is_recent(NOW - timedelta(hours=10), NOW) is True

    def test_outside_threshold(self):
        assert is_recent(NOW - timedelta(hours=25), NOW) is False

    def test_boundary_exactly_24h_inclusive(self):
        # 경계: 정확히 임계 시각은 통과(>=)
        assert is_recent(NOW - timedelta(hours=24), NOW) is True

    def test_future_time_passes(self):
        # 시계 오차로 인한 미래 시각도 통과
        assert is_recent(NOW + timedelta(hours=1), NOW) is True

    def test_none_uses_fallback(self):
        # published_at 없으면 fallback(수집 시각)으로 대체 → 방금 수집분은 통과
        assert is_recent(None, NOW, fallback=NOW) is True

    def test_both_none_excluded(self):
        assert is_recent(None, NOW, fallback=None) is False

    def test_custom_threshold(self):
        assert is_recent(NOW - timedelta(hours=10), NOW, threshold_hours=6) is False


# ── Step 4-A. 제목 중복 제거 ────────────────────────────────────────────────
class TestTitleBigrams:
    def test_multi_token_bigrams(self):
        assert title_bigrams("삼성전자 영업이익 증가") == {
            ("삼성전자", "영업이익"),
            ("영업이익", "증가"),
        }

    def test_single_token_falls_back_to_unigram(self):
        assert title_bigrams("삼성전자") == {("삼성전자",)}

    def test_punctuation_stripped(self):
        # 구두점 제거 후 토큰화
        assert title_bigrams("삼성, 전자!") == {("삼성", "전자")}


class TestJaccard:
    def test_identical_sets(self):
        s = {("a", "b"), ("b", "c")}
        assert jaccard(s, s) == 1.0

    def test_disjoint_sets(self):
        assert jaccard({("a", "b")}, {("c", "d")}) == 0.0

    def test_partial_overlap(self):
        a = {("a", "b"), ("b", "c")}
        b = {("a", "b"), ("b", "d")}
        assert jaccard(a, b) == 1 / 3  # 교집합 1 / 합집합 3

    def test_empty_returns_zero(self):
        assert jaccard(set(), {("a", "b")}) == 0.0


class TestDeduplicateByTitle:
    def test_removes_near_identical_titles(self):
        items = [
            _record("삼성전자 3분기 영업이익 10조 돌파", "https://a.com/1"),
            _record("삼성전자 3분기 영업이익 10조 돌파", "https://b.com/2"),  # 통신사 받아쓰기
        ]
        kept, dups = deduplicate_by_title(items)
        assert len(kept) == 1
        assert len(dups) == 1

    def test_different_angles_survive(self):
        items = [
            _record("삼성전자 3분기 영업이익 급증", "https://a.com/1"),
            _record("코스피 외국인 매수세 지속 상승", "https://b.com/2"),
        ]
        kept, dups = deduplicate_by_title(items)
        assert len(kept) == 2
        assert dups == []

    def test_keeps_latest_when_duplicate(self):
        older = _record("동일 제목 기사 입니다", "https://a.com/old", NOW - timedelta(hours=5))
        newer = _record("동일 제목 기사 입니다", "https://b.com/new", NOW - timedelta(hours=1))
        kept, dups = deduplicate_by_title([older, newer])
        assert kept[0]["url"] == "https://b.com/new"  # 최신 보존
        assert dups[0]["url"] == "https://a.com/old"

    def test_published_at_none_sorted_last(self):
        dated = _record("동일 제목 기사 입니다", "https://a.com/dated", NOW)
        undated = _record("동일 제목 기사 입니다", "https://b.com/undated", None)
        kept, _dups = deduplicate_by_title([undated, dated])
        assert kept[0]["url"] == "https://a.com/dated"  # 발행일 있는 기사 우선


# ── 파이프라인 조립 (run_preprocessing) ─────────────────────────────────────
class TestRunPreprocessing:
    def test_normalizes_and_keeps_clean_record(self):
        records = [_record("<b>삼성전자</b> 실적", "https://a.com/1?utm_source=naver")]
        result, stats = run_preprocessing(records, now=NOW)
        assert result[0]["title"] == "삼성전자 실적"
        assert result[0]["url"] == "https://a.com/1"
        assert result[0]["is_filtered"] is False
        assert stats.total == 1
        assert stats.kept == 1

    def test_old_record_flagged_not_dropped(self):
        records = [_record("오래된 기사 입니다", "https://a.com/1", NOW - timedelta(hours=30))]
        result, stats = run_preprocessing(records, now=NOW)
        assert len(result) == 1  # 삭제하지 않고 함께 반환
        assert result[0]["is_filtered"] is True
        assert stats.filtered_old == 1
        assert stats.kept == 0

    def test_duplicate_title_flagged(self):
        records = [
            _record("삼성전자 3분기 영업이익 10조 돌파", "https://a.com/1"),
            _record("삼성전자 3분기 영업이익 10조 돌파", "https://b.com/2"),
        ]
        result, stats = run_preprocessing(records, now=NOW)
        assert stats.filtered_dup == 1
        assert stats.kept == 1
        flagged = [r for r in result if r["is_filtered"]]
        assert len(flagged) == 1

    def test_old_records_excluded_from_dedup(self):
        # 24h 초과로 이미 탈락한 레코드는 제목 중복 집계에 포함되지 않는다
        records = [
            _record("동일 제목 기사 입니다", "https://a.com/1", NOW),
            _record("동일 제목 기사 입니다", "https://b.com/2", NOW - timedelta(hours=30)),
        ]
        _result, stats = run_preprocessing(records, now=NOW)
        assert stats.filtered_old == 1
        assert stats.filtered_dup == 0  # old 탈락분은 dedup 대상에서 빠짐
        assert stats.kept == 1

    def test_stats_sum_consistency(self):
        records = [
            _record("통과 기사 하나 입니다", "https://a.com/1"),
            _record("오래된 기사 둘 입니다", "https://a.com/2", NOW - timedelta(hours=30)),
            _record("통과 기사 하나 입니다", "https://b.com/3"),  # 1번과 제목 중복
        ]
        _result, stats = run_preprocessing(records, now=NOW)
        assert stats.kept + stats.filtered_old + stats.filtered_dup == stats.total

    def test_empty_input(self):
        result, stats = run_preprocessing([], now=NOW)
        assert result == []
        assert stats.total == 0
        assert stats.kept == 0

    def test_preserves_collected_fields(self):
        # 정규화·필터가 수집 필드(rss_source, news_source, published_at)를 보존하는지
        records = [_record("삼성전자 실적 발표", "https://a.com/1")]
        result, _stats = run_preprocessing(records, now=NOW)
        assert result[0]["rss_source"] == "hankyung"
        assert result[0]["news_source"] == "한국경제"
        assert result[0]["published_at"] == NOW

    def test_guid_kept_when_feed_provides(self):
        # 피드 제공 GUID는 그대로 수집-시점 중복키로 보존된다
        records = [{**_record("삼성전자 실적", "https://a.com/1"), "guid": "feed-guid-1"}]
        result, _stats = run_preprocessing(records, now=NOW)
        assert result[0]["guid"] == "feed-guid-1"

    def test_guid_falls_back_to_normalized_url(self):
        # 피드 GUID가 없으면 정규화 URL로 폴백 — 트래킹 파라미터가 키에 섞이지 않는다
        records = [_record("삼성전자 실적", "https://a.com/1?utm_source=naver")]
        result, _stats = run_preprocessing(records, now=NOW)
        assert result[0]["guid"] == "https://a.com/1"
