"""RSS 피드 목록 — 수집 대상 피드의 식별자·URL·언론사 상수 정의.

국내 증권 RSS 13개(DOMESTIC_SECURITIES_RSS) + investing.com 3개(GLOBAL_INVESTING_RSS)를
합쳐 ALL_FEEDS로 노출한다. 피드 추가·제거는 이 파일의 리스트만 수정하면 된다.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FeedSource:
    """수집 대상 RSS 피드 1개의 메타데이터."""

    url: str          # 실제 요청 보낼 RSS 주소
    rss_source: str   # 피드 식별자. 예: "hankyung_finance"
    # 기사에 <source>가 없을 때 news_source 폴백으로 쓰는 언론사명. 예: "한국경제"
    publisher: str
    # 오프셋 없는 발행시각을 해석할 기준 타임존. 국내 피드는 KST(기본), investing은 UTC.
    # 예: einfomax는 "2026-06-17 10:40:00"처럼 오프셋 없이 KST를 주므로 UTC로 보면 9h 밀린다.
    tz: str = "Asia/Seoul"


DOMESTIC_SECURITIES_RSS: list[FeedSource] = [
    FeedSource("https://www.hankyung.com/feed/finance", "hankyung_finance", "한국경제"),
    FeedSource("https://www.mk.co.kr/rss/50200011/", "mk_securities", "매일경제"),
    FeedSource("https://mbnmoney.mbn.co.kr/rss/news/stock", "mbn_stock", "매일경제TV"),
    FeedSource("https://news.einfomax.co.kr/rss/S1N2.xml", "einfomax", "연합인포맥스"),
    FeedSource(
        "https://www.thevaluenews.co.kr/rss_view.php?code=m6481nr",
        "thevaluenews_securities",
        "더밸류뉴스",
    ),
    FeedSource(
        "https://www.thevaluenews.co.kr/rss_view.php?code=m65gpg7",
        "thevaluenews_company",
        "더밸류뉴스",
    ),
    FeedSource("https://api.newswire.co.kr/rss/industry/203", "newswire", "뉴스와이어"),
    FeedSource("https://view.asiae.co.kr/rss/stock.htm", "asiae_stock", "아시아경제"),
    FeedSource("https://www.sedaily.com/rss/finance", "sedaily_finance", "서울경제"),
    FeedSource("https://www.newstomato.com/rss/?cate=12", "newstomato", "뉴스토마토"),
    FeedSource("http://rss.edaily.co.kr/stock_news.xml", "edaily_stock", "이데일리"),
    FeedSource(
        "https://www.fnnews.com/rss/r20/fn_realnews_stock.xml",
        "fnnews_stock",
        "파이낸셜뉴스",
    ),
    FeedSource("http://rss.newspim.com/news/category/105", "newspim", "뉴스핌"),
]

GLOBAL_INVESTING_RSS: list[FeedSource] = [
    # investing은 오프셋 없는 발행시각을 UTC로 준다(국내 피드와 달리 tz=UTC).
    FeedSource(
        "https://kr.investing.com/rss/news_1.rss", "investing_fx", "investing.com", tz="UTC"
    ),
    FeedSource(
        "https://kr.investing.com/rss/news_25.rss", "investing_stock", "investing.com", tz="UTC"
    ),
    FeedSource(
        "https://kr.investing.com/rss/news_95.rss", "investing_economy", "investing.com", tz="UTC"
    ),
]

ALL_FEEDS: list[FeedSource] = DOMESTIC_SECURITIES_RSS + GLOBAL_INVESTING_RSS
