"""뉴스 전처리 — 정규화 → 날짜 필터 → 제목 중복 제거 → DB 반영.

preprocessed_at IS NULL 레코드를 배치로 읽어 처리하고 preprocessed_at을 기록한다.
분석에서 제외할 레코드(24h 초과·제목 중복·URL 충돌)는 삭제하지 않고 is_filtered=True로
표시한다(보존 + 플래그). 본문·snippet은 저장하지 않으므로 HTML 정제는 title에만 적용한다.
타임존 정규화(설계 Step 2)는 수집 단계에서 KST naive로 처리돼 여기서는 다루지 않는다.

오케스트레이션(LangGraph 에이전트)은 Phase 7에서 run_preprocessing을 호출해 조립한다.
함수 구성: [정규화] → [날짜 필터] → [제목 중복 제거] → [파이프라인 조립].
"""

import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.queries import fetch_unprocessed_news, mark_news_preprocessed
from utils.dates import now_kst

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 500
DEFAULT_THRESHOLD_HOURS = 24       # 날짜 필터: 수집 시점 기준 허용 시간
DEFAULT_DUP_THRESHOLD = 0.8        # 제목 중복: bigram Jaccard 임계

# 제거 대상 트래킹 파라미터 (설계 04 §3.3)
TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid", "gclid", "ref", "source",
})

_TAG_PATTERN = re.compile(r"<[^>]+>")
_PUNCT_PATTERN = re.compile(r"[^\w\s]")


# ── 정규화 (Step 1·3) ───────────────────────────────────────────────────────
def clean_title(title: str) -> str:
    """제목의 HTML 엔티티를 디코드하고 태그를 제거한다.
    """
    if not title:
        return ""
    text = html.unescape(title)        # &amp; → &
    text = _TAG_PATTERN.sub("", text)  # <b> 등 태그 제거
    return text.strip()


def remove_tracking_params(url: str) -> str:
    """URL에서 트래킹 파라미터를 제거한다. 쿼리 순서는 보존한다.

    파싱 실패 시 원본 URL을 그대로 반환한다(설계 04 §6 — 계속 진행).
    """
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


# ── 날짜 필터 (Step 4) ──────────────────────────────────────────────────────
def is_recent(
    published_at: datetime | None,
    now: datetime,
    threshold_hours: int = DEFAULT_THRESHOLD_HOURS,
    *,
    fallback: datetime | None = None,
) -> bool:
    """published_at이 now로부터 threshold_hours 이내인지 판정한다(KST naive).

    published_at이 None이면 fallback(보통 created_at=수집 시각)으로 대체한다.
    둘 다 None이면 판정 불가로 보고 False(제외)를 반환한다.
    미래 시각(시계 오차 등)도 임계 범위 내로 간주해 통과시킨다.
    """
    reference = published_at or fallback
    if reference is None:
        return False
    return reference >= now - timedelta(hours=threshold_hours)


# ── 제목 중복 제거 (Step 5-B) ───────────────────────────────────────────────
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
    processed: int = 0       # 전처리 완료(=preprocessed_at 기록) 총건수
    kept: int = 0            # 분석 대상으로 통과
    filtered_old: int = 0    # 24h 초과로 제외
    filtered_dup: int = 0    # 제목 중복으로 제외
    url_conflicts: int = 0   # URL 정규화 후 기존 레코드와 충돌

    def merge(self, other: "PreprocessStats") -> None:
        self.processed += other.processed
        self.kept += other.kept
        self.filtered_old += other.filtered_old
        self.filtered_dup += other.filtered_dup
        self.url_conflicts += other.url_conflicts


@dataclass
class _Item:
    """배치 내 처리 단위 — ORM 객체에서 필요한 값만 추출해 담는다."""

    news_id: int
    title: str               # 정제된 title
    url: str                 # 정규화된 url
    original_url: str        # 정규화 전 url (충돌 시 폴백)
    published_at: datetime | None
    is_old: bool = False     # 날짜 필터 탈락
    is_dup: bool = False     # 제목 중복 탈락


async def preprocess_batch(
    db: AsyncSession,
    batch: list,
    now: datetime,
    threshold_hours: int,
) -> PreprocessStats:
    """배치 1개를 전처리하고 DB에 반영한다. commit까지 수행."""
    stats = PreprocessStats()

    # Step 1·3. 정규화 (HTML 제목 정제 + URL 트래킹 파라미터 제거)
    items: list[_Item] = []
    for news in batch:
        title, url = normalize(news.title, news.url)
        items.append(
            _Item(
                news_id=news.id,
                title=title,
                url=url,
                original_url=news.url,
                published_at=news.published_at,
            )
        )

    # Step 4. 날짜 필터 (발행일 없으면 created_at으로 대체)
    created_at_map = {news.id: news.created_at for news in batch}
    recent: list[_Item] = []
    for item in items:
        if is_recent(
            item.published_at, now, threshold_hours,
            fallback=created_at_map.get(item.news_id),
        ):
            recent.append(item)
        else:
            item.is_old = True

    # Step 5-B. 제목 유사도 중복 제거 (필터 통과분 대상)
    payloads = [{"_item": it, "title": it.title, "published_at": it.published_at} for it in recent]
    _, duplicates = deduplicate_by_title(payloads)
    dup_ids = {p["_item"].news_id for p in duplicates}
    for item in recent:
        if item.news_id in dup_ids:
            item.is_dup = True

    # DB 반영 — URL 정규화 충돌은 savepoint로 행 단위 격리.
    # 분류는 배타적: old > dup > conflict > kept (각 레코드 정확히 하나)
    for item in items:
        intended_filtered = item.is_old or item.is_dup
        conflicted = await _save_item(db, item, now, is_filtered=intended_filtered)

        stats.processed += 1
        if item.is_old:
            stats.filtered_old += 1
        elif item.is_dup:
            stats.filtered_dup += 1
        elif conflicted:
            # 통과 의도였으나 정규화 URL이 기존 레코드와 충돌 → 분석 제외
            stats.url_conflicts += 1
        else:
            stats.kept += 1

    await db.commit()
    return stats


async def _save_item(
    db: AsyncSession, item: _Item, now: datetime, *, is_filtered: bool
) -> bool:
    """전처리 결과 1건을 저장. URL 정규화 충돌이 있었으면 True를 반환한다.

    충돌 시 원본 URL을 유지하고 is_filtered=True로 표시한다. 원본 URL은 해당 레코드의
    현재 DB 값이라 자기 자신과만 비교되어 충돌하지 않지만, 만일을 대비해 폴백도 격리한다.
    """
    try:
        async with db.begin_nested():
            await mark_news_preprocessed(
                db, item.news_id,
                url=item.url, title=item.title,
                preprocessed_at=now, is_filtered=is_filtered,
            )
        return False
    except IntegrityError:
        pass
    try:
        async with db.begin_nested():
            await mark_news_preprocessed(
                db, item.news_id,
                url=item.original_url, title=item.title,
                preprocessed_at=now, is_filtered=True,
            )
    except IntegrityError:
        # 폴백마저 실패 — preprocessed_at만이라도 기록해 재조회 무한루프를 막는다
        logger.warning("전처리 저장 충돌(폴백 실패) news_id=%s", item.news_id)
        async with db.begin_nested():
            await mark_news_preprocessed(
                db, item.news_id,
                url=item.original_url, title=item.title,
                preprocessed_at=now, is_filtered=True,
            )
    return True


async def run_preprocessing(
    db: AsyncSession,
    batch_size: int = DEFAULT_BATCH_SIZE,
    threshold_hours: int = DEFAULT_THRESHOLD_HOURS,
) -> PreprocessStats:
    """미처리 뉴스를 모두 처리할 때까지 배치 단위로 반복한다."""
    total = PreprocessStats()
    while True:
        batch = await fetch_unprocessed_news(db, batch_size)
        if not batch:
            break
        # 24h 필터 기준 시각은 배치마다 갱신 — 다배치 장기 실행에서 기준 고정 방지
        now = now_kst()
        stats = await preprocess_batch(db, batch, now, threshold_hours)
        total.merge(stats)
        logger.info(
            "전처리 배치 완료 processed=%d kept=%d old=%d dup=%d conflict=%d",
            stats.processed, stats.kept, stats.filtered_old,
            stats.filtered_dup, stats.url_conflicts,
        )
    return total
