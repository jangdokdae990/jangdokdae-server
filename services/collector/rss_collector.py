"""RSS 피드 뉴스 수집기 — 파이프라인 '수집' 단계의 뉴스 진입점.

역할:
    16개 RSS 피드(국내 증권 13 + investing.com 3)를 병렬로 폴링해 기사
    제목·URL·출처·발행일을 수집한다. 본문·snippet은 저작권 리스크로 저장하지 않는다
    (본문은 분석 시점에 대표 기사만 실시간 fetch 후 폐기 — 설계 02 §3.4).

핵심 동작:
    - collect(): Semaphore(8)로 동시성을 제한해 피드를 병렬 수집. 피드 단위
      에러 격리(asyncio.gather(return_exceptions=True)) — 한 피드 실패가 전체를 막지 않는다.
    - news_source(본문 출처)와 rss_source(수집 피드)를 분리 저장. 집계형 피드는
      기사별 <source>를, 단일 언론사 피드는 feed.publisher를 폴백으로 쓴다.
    - 발행일은 KST naive datetime으로 정규화(struct_time → dateutil 폴백).

경계:
    입력 = rss_feeds.ALL_FEEDS / 출력 = CollectedNews.to_record() → save_tool.upsert_news.
    종목 코드(symbol)는 채우지 않는다 — 분석 단계의 Entity NER이 담당.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

import feedparser
import httpx
from dateutil import parser as date_parser

from services.collector.rss_feeds import ALL_FEEDS, FeedSource
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

    async def collect(self) -> tuple[list[CollectedNews], list[str]]:
        """수집 기사와 실패 피드 식별자를 함께 반환한다.

        실패 피드를 반환값으로 끌어올려 단계 경계(NewsCollector)에서 부분 실패를
        구조적으로 인지하게 한다 — 16개 중 다수가 조용히 죽어도 Task는 성공으로 끝나기에,
        로그에만 두면 수집량 급감을 놓친다(설계 02 §7.2).
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
                # _fetch_feed가 예외를 전파하므로 HTTP 실패·예기치 못한 예외가 모두 여기로 모인다.
                logger.warning(
                    "RSS 피드 수집 실패 rss_source=%s err=%s", feed.rss_source, batch
                )
                failed_feeds.append(feed.rss_source)
                continue
            collected.extend(batch)
        return collected, failed_feeds

    async def _fetch_feed(
        self, client: httpx.AsyncClient, feed: FeedSource
    ) -> list[CollectedNews]:
        # HTTP 실패는 잡지 않고 전파한다 — collect()의 gather가 피드 단위로 격리·분류해
        # failed_feeds에 모은다(실패와 '빈 피드'를 구분하기 위함).
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
        # 비정상 피드가 <source>를 비-dict로 줄 수 있어 타입 가드 (AttributeError 방지)
        source = entry.get("source")
        if isinstance(source, dict) and source.get("title"):
            return str(source["title"])
        return feed.publisher

    @staticmethod
    def _parse_published(
        entry: feedparser.FeedParserDict, feed: FeedSource
    ) -> datetime | None:
        """발행일을 한국 시간(KST) datetime으로 반환. 없거나 파싱 실패 시 None."""
        # 1) feedparser가 파싱한 struct_time(UTC) 우선. <pubDate> 없으면 <dc:date>/<updated>
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed_time:
            # 깨진 struct_time(범위 밖 연·월 등)도 한 기사 때문에 피드 전체가 유실되지
            # 않도록 변환 실패를 격리하고 2) 문자열 폴백으로 넘긴다.
            try:
                utc_dt = datetime(*parsed_time[:6], tzinfo=timezone.utc)  # type: ignore[misc]
                return to_naive_kst(utc_dt)
            except (ValueError, TypeError):
                logger.debug("struct_time 변환 실패 rss_source=%s", feed.rss_source)

        # 2) struct_time이 없으면 원본 문자열을 직접 파싱.
        #    일부 피드(예: 파이낸셜뉴스 'Mon,1 Jun ...')는 비표준 형식이라 feedparser가 못 읽음
        raw = entry.get("published") or entry.get("updated")
        if raw:
            try:
                parsed: datetime = date_parser.parse(raw)
            except (ValueError, OverflowError, TypeError):
                logger.debug("발행일 파싱 실패 rss_source=%s raw=%s", feed.rss_source, raw)
                return None
            # 오프셋 없는 시각은 UTC로 가정 — struct_time 경로(항상 UTC)와 기준을 일치시켜
            # 동일 시각이 경로에 따라 9시간 어긋나는 것을 방지
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return to_naive_kst(parsed)

        logger.debug("발행일 없음 rss_source=%s", feed.rss_source)
        return None
