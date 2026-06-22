"""뉴스 전처리 — 수집 결과를 인메모리로 정제해 저장 직전 단계로 넘긴다.

수집 리스트를 받아 [HTML 정제 → URL 정규화 → 날짜 필터 → 제목 중복 제거]를 인메모리로 적용한다.
분석에서 제외할 레코드(24h 초과·제목 중복)는 삭제하지 않고 is_filtered=True로 표시해 반환한다.

타임존 정규화는 수집 단계에서 끝나므로 여기서 다루지 않는다. 본문·snippet은 저장하지 않으므로
HTML 정제는 title에만 적용한다.
"""

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from utils.dates import now_kst

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD_HOURS = 24       # 날짜 필터: 수집 시점 기준 허용 시간
DEFAULT_DUP_THRESHOLD = 0.8        # 제목 중복: bigram Jaccard 임계

# 제거 대상 트래킹 파라미터
TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid", "gclid", "ref", "source",
})

_TAG_PATTERN = re.compile(r"<[^>]+>")
_PUNCT_PATTERN = re.compile(r"[^\w\s]")


# ── 정규화 (Step 1·2) ───────────────────────────────────────────────────────
def clean_title(title: str) -> str:
    """제목의 HTML 엔티티를 디코드하고 태그를 제거한다. 비문자열·빈 입력은 빈 문자열로 방어."""
    if not isinstance(title, str) or not title:
        return ""
    text = html.unescape(title)        # &amp; → &
    text = _TAG_PATTERN.sub("", text)  # <b> 등 태그 제거
    return text.strip()


def remove_tracking_params(url: str) -> str:
    """URL에서 트래킹 파라미터를 제거한다. 쿼리 순서는 보존, 파싱 실패 시 원본 URL을 반환한다."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        kept = [
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if k not in TRACKING_PARAMS
        ]
        return urlunparse(parsed._replace(query=urlencode(kept)))
    except ValueError:
        return url


def normalize(title: str, url: str) -> tuple[str, str]:
    """(정제된 title, 정규화된 url) 쌍을 반환한다."""
    return clean_title(title), remove_tracking_params(url)


# ── 날짜 필터 (Step 3) ──────────────────────────────────────────────────────
def is_recent(
    published_at: datetime | None,
    now: datetime,
    threshold_hours: int = DEFAULT_THRESHOLD_HOURS,
    *,
    fallback: datetime | None = None,
) -> bool:
    """published_at이 now로부터 threshold_hours 이내인지 판정한다(KST naive).

    published_at이 None이면 fallback(수집 시각)으로 대체한다.
    둘 다 None이면 판정 불가로 보고 False(제외)를 반환한다.
    미래 시각(시계 오차 등)도 임계 범위 내로 간주해 통과시킨다.
    """
    reference = published_at or fallback
    if reference is None:
        return False
    return reference >= now - timedelta(hours=threshold_hours)


# ── 제목 중복 제거 (Step 4) ─────────────────────────────────────────────────
def title_bigrams(title: str) -> set[tuple[str, ...]]:
    """제목을 토큰 bigram 집합으로 변환한다. 토큰이 1개뿐이면 unigram으로 폴백."""
    tokens = _PUNCT_PATTERN.sub("", title).split()
    if len(tokens) > 1:
        return set(zip(tokens, tokens[1:]))
    return {(t,) for t in tokens}


def jaccard(a: set, b: set) -> float:
    """두 집합의 Jaccard 유사도. 한쪽이라도 비면 0.0."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _dedup_sort_key(item: dict) -> tuple[bool, datetime]:
    # 발행일 있는 기사를 우선(True), 그 안에서 최신순. None은 datetime.min으로 뒤로.
    published_at = item.get("published_at")
    return (published_at is not None, published_at or datetime.min)


def deduplicate_by_title(
    items: list[dict],
    threshold: float = DEFAULT_DUP_THRESHOLD,
) -> tuple[list[dict], list[dict]]:
    """제목 유사도로 중복을 제거한다. (보존, 중복) 두 리스트를 반환한다.

    최신 기사를 우선 보존한다. 동일 제목이면 발행일 있는 기사가 대표로 남는다.
    각 dict는 최소 "title", "published_at" 키를 가진다고 가정한다.
    반환 리스트는 입력 dict 객체를 그대로 참조한다(복사하지 않음).
    """
    sorted_items = sorted(items, key=_dedup_sort_key, reverse=True)
    kept: list[tuple[set, dict]] = []
    duplicates: list[dict] = []
    for item in sorted_items:
        bigrams = title_bigrams(item["title"])
        if any(jaccard(bigrams, seen) >= threshold for seen, _ in kept):
            duplicates.append(item)
        else:
            kept.append((bigrams, item))
    return [item for _, item in kept], duplicates


# ── 파이프라인 조립 ─────────────────────────────────────────────────────────
@dataclass
class PreprocessStats:
    total: int = 0           # 입력 레코드 수
    kept: int = 0            # 분석 대상으로 통과 (is_filtered=False)
    filtered_old: int = 0    # 24h 초과로 제외
    filtered_dup: int = 0    # 제목 중복으로 제외


def run_preprocessing(
    records: list[dict],
    *,
    now: datetime | None = None,
    threshold_hours: int = DEFAULT_THRESHOLD_HOURS,
    dup_threshold: float = DEFAULT_DUP_THRESHOLD,
) -> tuple[list[dict], PreprocessStats]:
    """수집 레코드를 정제해 (저장용 레코드, 통계)를 반환한다. DB 접근 없음.

    records: CollectedNews.to_record() 형식 — title, url, rss_source, news_source, published_at.
    반환 레코드: 위 필드 + is_filtered. created_at·preprocessed_at은 저장 시 DB 기본값/NULL.
    탈락(24h·제목 중복) 레코드도 삭제하지 않고 is_filtered=True로 반환한다.
    """
    now = now or now_kst()
    stats = PreprocessStats(total=len(records))

    # Step 1·2. 정규화 (HTML 제목 정제 + URL 트래킹 파라미터 제거)
    # guid 폴백: 피드 GUID가 없으면 정규화 URL을 수집-시점 중복키로 쓴다(설계 02 §7).
    # URL 정규화 후에 폴백을 채워 트래킹 파라미터가 키에 섞이지 않게 한다.
    items: list[dict] = []
    for r in records:
        title, url = normalize(r["title"], r["url"])
        items.append({
            **r, "title": title, "url": url,
            "guid": r.get("guid") or url, "is_filtered": False,
        })

    # Step 3. 날짜 필터 — 발행일 없으면 수집 시각(now)으로 대체
    for item in items:
        if not is_recent(item.get("published_at"), now, threshold_hours, fallback=now):
            item["is_filtered"] = True
            stats.filtered_old += 1

    # Step 4. 제목 유사도 중복 제거 (필터 통과분만 대상)
    survivors = [item for item in items if not item["is_filtered"]]
    _, duplicates = deduplicate_by_title(survivors, threshold=dup_threshold)
    for dup in duplicates:  # deduplicate_by_title은 동일 dict 객체를 반환
        dup["is_filtered"] = True
        stats.filtered_dup += 1

    stats.kept = stats.total - stats.filtered_old - stats.filtered_dup
    logger.info(
        "전처리 완료 total=%d kept=%d old=%d dup=%d",
        stats.total, stats.kept, stats.filtered_old, stats.filtered_dup,
    )
    return items, stats
