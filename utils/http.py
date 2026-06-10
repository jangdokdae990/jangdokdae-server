"""앱·서비스 공용 HTTP 상수 — 외부 요청 시 여러 모듈이 공유하는 무상태 값.

USER_AGENT: RSS 폴링(rss_collector)·본문 fetch(analyzer.article_fetcher) 등 여러 단계의
httpx 클라이언트가 공유한다. 일부 언론사 서버가 기본 UA를 차단하므로 일반 브라우저 UA를 보낸다.
특정 단계 모듈에 두면 다른 단계가 그 모듈을 가로질러 import해야 하므로 공용 utils에 둔다.
"""

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
