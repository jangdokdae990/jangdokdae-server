# RSS 수집기 (3-1) 설계

**작성일** 2026-06-01
**범위** Phase 3-1 — `services/collector/rss_collector.py` 구현
**관련 문서**
- [뉴스 데이터 수집 기획서](../../design/02-news-collection-design.md)
- [코드 컨벤션](../../conventions.md)

---

## 1. 목표

설계 문서 4.2에 정의된 **고정 RSS 피드 16개**(국내 증권 13개 + investing.com 글로벌 3개)에서
뉴스의 제목·URL·출처·발행일을 비동기로 수집해 `list[dict]`로 반환하는 수집기를 구현한다.

- DB 저장은 본 모듈의 책임이 아니다. 저장(UPSERT)은 Phase 5의 `save_tool.py`가 담당한다.
- 따라서 본 모듈은 Phase 0/1(설정 로더·DB 세션·`News` 모델) 없이 **독립적으로 구현·테스트 가능**하다.

## 2. 선행 결정 사항

| 항목 | 결정 | 비고 |
|------|------|------|
| HTTP 클라이언트 | **httpx** (비동기) | `pyproject.toml`에 `httpx` 추가, `aiohttp`는 미사용 시 제거 검토 |
| 발행일 처리 | **datetime(UTC)으로 파싱** | `feedparser`의 `published_parsed`(struct_time)를 UTC datetime으로 변환 |
| 출처 필드 | **`rss` + `source` 2개로 분리** | `region`/`source_type`/`symbol`/시장·종목 구분은 수집기에서 다루지 않음 |

### 2.1 출처 필드 분리

수집기는 출처를 두 개념으로 분리해 기록한다.

- **`rss`**: 16개 피드 중 **어느 RSS에서 폴링했는지** (우리가 부여하는 피드 식별자)
- **`source`**: **뉴스 기사 본문의 실제 출처(언론사)**

## 3. 수집 대상 RSS (16개)

설계 문서 4.2의 고정 피드를 그대로 사용한다.

### 국내 증권 RSS (13개)

| rss(식별자) | publisher | URL |
|------|------|-----|
| `hankyung_finance` | 한국경제 | `https://www.hankyung.com/feed/finance` |
| `mk_securities` | 매일경제 | `https://www.mk.co.kr/rss/50200011/` |
| `mbn_stock` | 매일경제TV | `https://mbnmoney.mbn.co.kr/rss/news/stock` |
| `einfomax` | 연합인포맥스 | `https://news.einfomax.co.kr/rss/S1N2.xml` |
| `thevaluenews_securities` | 더밸류뉴스 | `https://www.thevaluenews.co.kr/rss_view.php?code=m6481nr` |
| `thevaluenews_company` | 더밸류뉴스 | `https://www.thevaluenews.co.kr/rss_view.php?code=m65gpg7` |
| `newswire` | 뉴스와이어 | `https://api.newswire.co.kr/rss/industry/203` |
| `asiae_stock` | 아시아경제 | `https://view.asiae.co.kr/rss/stock.htm` |
| `sedaily_finance` | 서울경제 | `https://www.sedaily.com/rss/finance` |
| `newstomato` | 뉴스토마토 | `https://www.newstomato.com/rss/?cate=12` |
| `edaily_stock` | 이데일리 | `http://rss.edaily.co.kr/stock_news.xml` |
| `fnnews_stock` | 파이낸셜뉴스 | `https://www.fnnews.com/rss/r20/fn_realnews_stock.xml` |
| `newspim` | 뉴스핌 | `http://rss.newspim.com/news/category/105` |

### 글로벌 investing.com RSS (3개)

| rss(식별자) | publisher | URL | 용도 |
|------|------|-----|------|
| `investing_fx` | investing.com | `https://kr.investing.com/rss/news_1.rss` | 환율 |
| `investing_stock` | investing.com | `https://kr.investing.com/rss/news_25.rss` | 해외 주식시장 |
| `investing_economy` | investing.com | `https://kr.investing.com/rss/news_95.rss` | 경제지표 |

> 피드 추가·제거는 이 상수 목록만 수정하면 되도록 한다.

## 4. 컴포넌트 설계

### 4.1 FeedSource

```python
@dataclass(frozen=True)
class FeedSource:
    url: str
    rss: str          # 어느 RSS 피드인지: "hankyung_finance" ...
    publisher: str    # 피드의 기본 언론사명: "한국경제" ... (source 폴백용)
```

피드 목록은 모듈 상수로 정의한다.

```python
DOMESTIC_SECURITIES_RSS: list[FeedSource] = [...]   # 13개
GLOBAL_INVESTING_RSS:    list[FeedSource] = [...]   # 3개
ALL_FEEDS = DOMESTIC_SECURITIES_RSS + GLOBAL_INVESTING_RSS
```

### 4.2 RSSCollector

```python
class RSSCollector:
    def __init__(
        self,
        feeds: list[FeedSource] | None = None,   # 기본값 ALL_FEEDS
        max_concurrency: int = 5,
        timeout: float = 10.0,
    ) -> None: ...

    async def collect(self) -> list[dict]:
        """전체 피드를 동시 수집해 정규화된 dict 리스트 반환 (public)"""

    async def _fetch_feed(self, client: httpx.AsyncClient, feed: FeedSource) -> list[dict]:
        """단일 피드 수집·파싱. 실패 시 빈 리스트 반환 (에러 격리)"""
```

상수(매직 넘버 금지): `max_concurrency`, `timeout`, `User-Agent` 헤더는 모듈 상수 또는 기본 파라미터로 둔다.

## 5. 데이터 흐름

```
collect()
  └─ httpx.AsyncClient 생성
  └─ asyncio.Semaphore(max_concurrency)
  └─ 각 feed에 대해 _fetch_feed() 동시 실행
        └─ httpx GET (timeout, User-Agent 헤더)
        └─ feedparser.parse(response.text)
        └─ entry마다 dict 변환
  └─ 모든 피드 결과를 flatten 해 반환
```

### 5.1 반환 dict

```python
{
    "title":        str,                # entry.title
    "url":          str,                # entry.link
    "rss":          str,                # feed.rss (어느 RSS인지)
    "source":       str,                # 본문 출처: entry.source.title 또는 feed.publisher
    "published_at": datetime | None,    # published_parsed → UTC datetime
}
```

### 5.2 source(본문 출처) 추출

```python
source = entry.get("source", {}).get("title") or feed.publisher
```

- RSS `<source>` 요소가 있으면 그 값을 우선 사용한다(집계형 피드: 뉴스와이어, investing.com).
- 없으면 피드에 설정된 `publisher`로 폴백한다(단일 언론사 피드: 한국경제, 이데일리 등).
- 이유: 단일 언론사 피드는 `<source>`가 비어 있어, 폴백이 없으면 본문 출처가 누락된다.

### 5.3 published_at 변환

```python
# feedparser는 published_parsed를 time.struct_time(UTC 기준)으로 제공
if entry.get("published_parsed"):
    published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
else:
    published_at = None   # 다운스트림(Phase 4 normalizer)에서 처리
```

## 6. 에러 처리 (격리 원칙)

| 상황 | 대응 |
|------|------|
| 피드 타임아웃 / 네트워크 오류 / 4xx·5xx | 해당 `_fetch_feed`가 빈 리스트 반환 + `warning` 로깅. 나머지 피드는 정상 |
| `feedparser` 파싱 실패(`feed.bozo`) | 가능한 엔트리만 수집, 경고 로깅 |
| `title` 또는 `url`이 비어 있는 엔트리 | 해당 엔트리 스킵 |
| `published_parsed` 없음/파싱 실패 | `published_at=None` + `debug` 로깅 |

- 동시 요청은 세마포어로 `max_concurrency`(기본 5)개로 제한해 대상 서버 부하를 방지한다.
- 피드 단위 try/except로 격리하며, `asyncio.gather`로 전체를 실패시키지 않는다.
- 빈 catch 블록 금지 — 모든 예외는 구체적으로 잡고 로깅한다.

## 7. 테스트 (TDD)

네트워크 실제 호출 없이 고정 RSS 샘플 XML 픽스처와 모킹으로 검증한다.

| 테스트 | 검증 내용 |
|--------|----------|
| 정상 피드 파싱 | 샘플 XML → 올바른 dict 리스트 (title/url/rss/source/published_at) |
| 메타데이터 매핑 | `rss`·`publisher`가 FeedSource 설정대로 채워지는지 |
| source 폴백 | `<source>` 있으면 그 값, 없으면 `publisher` |
| 빈 title/url 스킵 | 불완전 엔트리 제외 |
| published 파싱 | `published_parsed` 있음→UTC datetime, 없음→None |
| 피드 단위 에러 격리 | 한 피드 예외 발생 시 나머지 피드 결과는 정상 반환 |

## 8. 의존성 변경

| 변경 | 내용 |
|------|------|
| 추가 | `httpx` (`pyproject.toml`) |
| 제거 검토 | `aiohttp` — 다른 모듈에서 사용하지 않으면 제거 |

## 9. 범위 밖 (다른 Phase)

- DB 저장(UPSERT): Phase 5 `save_tool.py`
- 정규화(HTML 정제·타임존·트래킹 파라미터 제거): Phase 4-1 `normalizer.py`
- 24시간 날짜 필터: Phase 4-2 `filter.py`
- 중복 제거: Phase 4-3 `deduplicator.py`
- 종목 태깅(`symbol`): 분석 파이프라인 Entity NER
- LangGraph 에이전트 통합: Phase 7-1 `news_collection_agent.py`
