"""RSS 피드 뉴스 수집기 — 국내 증권 섹션 피드(config/news_feeds.yaml)를 병렬 폴링.

기사 제목·URL·출처·발행일만 수집한다(본문·snippet은 저작권 문제로 저장하지 않음).
비기사성 뉴스(AI 요약 카드뉴스·부고 등)는 기자 기사가 아니므로 수집 단계에서 제외한다.
Semaphore로 동시성을 제한하고 피드 단위로 에러를 격리한다. 발행일은 KST naive
datetime으로 정규화한다(원본 문자열 파싱 우선, 오프셋 없으면 feed.tz로 해석 → struct_time 폴백).
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import feedparser
import httpx
from dateutil import parser as date_parser

from services.collector.news_filter import is_excluded
from services.collector.rss_feeds import ALL_FEEDS, FeedSource
from services.collector.tools.with_retry import with_retry
from utils.dates import to_naive_kst
from utils.http import USER_AGENT

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENCY = 8
DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class CollectedNews:
    title: str
    url: str
    rss_source: str            # 어느 RSS 피드에서 수집했는지 (피드 식별자)
    news_source: str           # 기사 본문의 실제 출처(언론사)
    published_at: datetime | None   # 발행 시각 (KST). 피드에 없으면 None
    # 피드 제공 GUID(<guid>). 없으면 None → 전처리에서 정규화 URL로 폴백(수집-시점 중복키).
    guid: str | None = None

    def to_record(self) -> dict[str, str | datetime | None]:
        # News 컬럼 입력 형식. guid 폴백(None→정규화 URL)은 전처리에서 채운다.
        return {
            "title": self.title,
            "url": self.url,
            "rss_source": self.rss_source,
            "news_source": self.news_source,
            "published_at": self.published_at,
            "guid": self.guid,
        }


class RSSCollector:
    def __init__(
        self,
        feeds: list[FeedSource] | None = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.feeds = feeds if feeds is not None else ALL_FEEDS
        self.max_concurrency = max_concurrency
        self.timeout = timeout

    async def collect(self) -> tuple[list[CollectedNews], list[str]]:
        """수집 기사와 실패 피드 식별자를 함께 반환한다.

        실패 피드를 반환값으로 올려 호출부가 부분 실패를 인지하게 한다 — 로그에만
        두면 다수 피드가 조용히 죽어도 수집량 급감을 놓친다.
        """
        semaphore = asyncio.Semaphore(self.max_concurrency)
        headers = {"User-Agent": USER_AGENT}

        async with httpx.AsyncClient(timeout=self.timeout, headers=headers) as client:

            async def fetch_with_semaphore(feed: FeedSource) -> list[CollectedNews]:
                async with semaphore:
                    return await self._fetch_feed(client, feed)

            batches = await asyncio.gather(
                *[fetch_with_semaphore(feed) for feed in self.feeds],
                return_exceptions=True,
            )

        collected: list[CollectedNews] = []
        failed_feeds: list[str] = []
        for feed, batch in zip(self.feeds, batches):
            if isinstance(batch, BaseException):
                # 피드 단위 격리 — 한 피드 실패가 전체 수집을 멈추지 않는다.
                logger.warning(
                    "RSS 피드 수집 실패 rss_source=%s err=%s", feed.rss_source, batch
                )
                failed_feeds.append(feed.rss_source)
                continue
            collected.extend(batch)
        return collected, failed_feeds

    @with_retry(max_attempts=2, retry_on=httpx.TransportError)
    async def _fetch_feed(
        self, client: httpx.AsyncClient, feed: FeedSource
    ) -> list[CollectedNews]:
        # 일시 네트워크 오류(TransportError)는 with_retry가 한 번 더 시도해 흡수한다 —
        # 24h 윈도우라 한 사이클 누락이 일부 영구 손실이 될 수 있다. 재시도 소진·그 외
        # 실패(4xx/5xx 등)는 전파해 collect()가 피드 단위로 격리·분류한다.
        response = await client.get(feed.url)
        response.raise_for_status()

        parsed = feedparser.parse(response.text)
        if parsed.bozo:
            logger.warning(
                "RSS 파싱 경고 rss_source=%s err=%s", feed.rss_source, parsed.bozo_exception
            )

        collected: list[CollectedNews] = []
        for entry in parsed.entries:
            title = entry.get("title", "").strip()
            url = entry.get("link", "").strip()
            if not title or not url:
                continue
            summary = entry.get("summary", "") or entry.get("description", "")
            if is_excluded(title, summary):
                logger.info(
                    "비기사성 뉴스 제외 rss_source=%s title=%s", feed.rss_source, title
                )
                continue
            collected.append(
                CollectedNews(
                    title=title,
                    url=url,
                    rss_source=feed.rss_source,
                    news_source=self._extract_source(entry, feed),
                    published_at=self._parse_published(entry, feed),
                    guid=self._extract_guid(entry),
                )
            )
        if not collected:
            # HTTP 200인데 기사가 0건 — 피드 포맷 변경·폐쇄로 인한 '조용한 실패' 신호.
            # 피드 단위 실패(failed_feeds)로는 안 잡히므로 별도 경보로 끌어올린다.
            logger.warning(
                "RSS 피드 0건 수집 — 포맷 변경·폐쇄 의심 rss_source=%s", feed.rss_source
            )
        return collected

    @staticmethod
    def _extract_guid(entry: feedparser.FeedParserDict) -> str | None:
        """피드 제공 GUID(<guid>/<id>)를 반환한다. 없거나 빈 값이면 None.

        feedparser는 <guid>를 entry.id로 매핑한다. 비어 있으면 None을 돌려보내
        전처리가 정규화 URL로 폴백하게 한다(수집-시점 정확 중복키 — 설계 02 §7).
        """
        guid = entry.get("id")
        if isinstance(guid, str) and guid.strip():
            return guid.strip()
        return None

    @staticmethod
    def _extract_source(entry: feedparser.FeedParserDict, feed: FeedSource) -> str:
        """기사 본문 출처(news_source)를 결정한다.

        기사 <source>가 있으면 그 값을, 없으면 feed.publisher를 폴백으로 쓴다.
        """
        # 비정상 피드가 <source>를 비-dict로 줄 수 있어 타입 가드 (AttributeError 방지)
        source = entry.get("source")
        if isinstance(source, dict) and source.get("title"):
            return str(source["title"])
        return feed.publisher

    @staticmethod
    def _parse_published(
        entry: feedparser.FeedParserDict, feed: FeedSource
    ) -> datetime | None:
        """발행일을 한국 시간(KST naive) datetime으로 반환. 없거나 파싱 실패 시 None.

        원본 문자열을 직접 파싱해 명시 오프셋(+0900 등)을 그대로 존중하고, 오프셋이 없는
        시각은 피드 기준 타임존(feed.tz, 국내 섹션 피드는 모두 KST)으로 해석한다. feedparser의
        struct_time은 오프셋 없는 입력을 UTC로 가정해버려 국내 피드(예: einfomax)의 KST 시각이
        9시간 밀리므로, 문자열 파싱을 우선하고 struct_time은 폴백으로만 쓴다.
        """
        # 1) 원본 문자열 직접 파싱 — 명시 오프셋 존중, 없으면 feed.tz로 해석
        raw = entry.get("published") or entry.get("updated")
        if raw:
            try:
                parsed: datetime | None = date_parser.parse(raw)
            except (ValueError, OverflowError, TypeError):
                logger.debug("발행일 문자열 파싱 실패 rss_source=%s raw=%s", feed.rss_source, raw)
                parsed = None
            if parsed is not None:
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=ZoneInfo(feed.tz))
                return to_naive_kst(parsed)

        # 2) 문자열이 없거나 파싱 실패 — feedparser struct_time(UTC) 폴백
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed_time:
            try:
                utc_dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)  # type: ignore[misc]
                return to_naive_kst(utc_dt)
            except (ValueError, TypeError):
                logger.debug("struct_time 변환 실패 rss_source=%s", feed.rss_source)

        logger.debug("발행일 없음 rss_source=%s", feed.rss_source)
        return None
