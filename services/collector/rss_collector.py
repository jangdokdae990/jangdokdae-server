"""RSS 피드 뉴스 수집기"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import httpx
from dateutil import parser as date_parser

from services.collector.rss_feeds import ALL_FEEDS, FeedSource
from utils.dates import to_naive_kst

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_MAX_CONCURRENCY = 8
DEFAULT_TIMEOUT = 10.0


@dataclass(frozen=True)
class CollectedNews:
    title: str
    url: str
    rss_source: str            # 어느 RSS 피드에서 수집했는지 (피드 식별자)
    news_source: str           # 기사 본문의 실제 출처(언론사)
    published_at: datetime | None   # 발행 시각 (KST). 피드에 없으면 None

    def to_record(self) -> dict[str, str | datetime | None]:
        # 오케스트레이션 경계: NewsAgentState.collected / save_tool.upsert_news 입력 형식
        return {
            "title": self.title,
            "url": self.url,
            "rss_source": self.rss_source,
            "news_source": self.news_source,
            "published_at": self.published_at,
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

    async def collect(self) -> list[CollectedNews]:
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
        for feed, batch in zip(self.feeds, batches):
            if isinstance(batch, BaseException):
                # 예기치 못한 예외도 피드 단위로 격리 — 전체 수집을 멈추지 않는다
                logger.error(
                    "RSS 피드 수집 중 예외 rss_source=%s err=%s", feed.rss_source, batch
                )
                continue
            collected.extend(batch)
        return collected

    async def _fetch_feed(
        self, client: httpx.AsyncClient, feed: FeedSource
    ) -> list[CollectedNews]:
        try:
            response = await client.get(feed.url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # 피드 단위 격리 — 한 피드 실패가 전체 수집을 멈추지 않도록 한다
            logger.warning(
                "RSS 피드 수집 실패 rss_source=%s url=%s err=%s",
                feed.rss_source,
                feed.url,
                exc,
            )
            return []

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
            collected.append(
                CollectedNews(
                    title=title,
                    url=url,
                    rss_source=feed.rss_source,
                    news_source=self._extract_source(entry, feed),
                    published_at=self._parse_published(entry, feed),
                )
            )
        return collected

    @staticmethod
    def _extract_source(entry: feedparser.FeedParserDict, feed: FeedSource) -> str:
        """기사 본문 출처(news_source)를 결정한다.

        집계형 피드(뉴스와이어·investing.com)는 기사마다 <source>에 원 언론사가 담겨
        그 값을 쓴다. 단일 언론사 피드(한국경제 등)는 <source>가 비어 있어,
        피드에 설정된 feed.publisher를 폴백으로 채운다.
        """
        source = entry.get("source") or {}
        return source.get("title") or feed.publisher

    @staticmethod
    def _parse_published(
        entry: feedparser.FeedParserDict, feed: FeedSource
    ) -> datetime | None:
        """발행일을 한국 시간(KST) datetime으로 반환. 없거나 파싱 실패 시 None."""
        # 1) feedparser가 파싱한 struct_time(UTC) 우선. <pubDate> 없으면 <dc:date>/<updated>
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed_time:
            utc_dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)  # type: ignore[misc]
            return to_naive_kst(utc_dt)

        # 2) struct_time이 없으면 원본 문자열을 직접 파싱.
        #    일부 피드(예: 파이낸셜뉴스 'Mon,1 Jun ...')는 비표준 형식이라 feedparser가 못 읽음
        raw = entry.get("published") or entry.get("updated")
        if raw:
            try:
                parsed: datetime = date_parser.parse(raw)
            except (ValueError, OverflowError):
                logger.debug("발행일 파싱 실패 rss_source=%s raw=%s", feed.rss_source, raw)
                return None
            return to_naive_kst(parsed)

        logger.debug("발행일 없음 rss_source=%s", feed.rss_source)
        return None
