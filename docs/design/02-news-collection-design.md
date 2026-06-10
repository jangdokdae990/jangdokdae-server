# 뉴스 데이터 수집 기획서

> **작성자** Kim minkyoung · **작성일** 2026-05-28
>
> **범위** 뉴스 수집 → 전처리 → 임베딩
>
> **관련 문서**
>
> - [파이프라인 오케스트레이션](./01-pipeline-orchestration-design.md)
> - [전처리 기획서](./04-preprocessing-design.md)

---

## 목차

- [1. 개요](#1-개요)
- [2. 수집 대상 정의](#2-수집-대상-정의)
- [3. 저작권 및 법적 검토](#3-저작권-및-법적-검토)
- [4. 수집 소스 검토](#4-수집-소스-검토)
- [5. 수집 방법](#5-수집-방법)
- [6. 주요 뉴스 선정 — 클러스터링 단계 담당](#6-주요-뉴스-선정--클러스터링-단계-담당)
- [7. 뉴스 수집 단계](#7-뉴스-수집-단계)
- [8. 데이터 명세](#8-데이터-명세)
- [9. 수집 주기](#9-수집-주기)
- [10. 시스템 아키텍처](#10-시스템-아키텍처)
- [11. 구현 로드맵](#11-구현-로드맵)
- [12. 미결 사항](#12-미결-사항)
- [참고 자료](#참고-자료)

---

## 1. 개요

### 1.1 서비스에서 뉴스 데이터의 역할

장독대는 주식 초보자(주린이)가 복잡한 시장 뉴스를 쉽게 이해할 수 있도록 LLM이 뉴스를 분석하고 쉬운 언어로 풀어주는 서비스다. 뉴스 데이터는 이 서비스의 **가장 중요한 원재료**다.

뉴스는 다음 네 가지 기능에 모두 활용된다.

| 기능 | 뉴스 데이터의 역할 |
|------|-----------------|
| 주린이용 풀이 생성 | LLM이 뉴스를 읽고 쉬운 언어로 재설명 |
| 오늘의 주요 이슈 파악 | 중요도 필터링 + 클러스터링으로 핵심 이슈 선별 |
| 관심 종목 뉴스 피드 | 사용자별 관심 종목 관련 최신 뉴스 제공 |
| Issue Docent 생성 | 유사 뉴스를 묶어 하나의 이슈로 요약 |

### 1.2 수집 목표

- **수집 범위**: 국내 주식·증권 + 해외 글로벌 경제
- **수집 방법**: 고정 RSS 피드만 사용 (API 키 불필요, 키워드 검색 없음)
- **저장 방식**: 제목 + URL + 메타데이터 (본문·snippet 저장 없음)
- **본문 활용**: 분석 시점에 대표 기사만 실시간 fetch 후 폐기

### 1.3 일별 수집량 추정

고정 RSS 피드를 주기적으로 폴링한다. 키워드 검색 없이 **피드 수 × 건당 반환**이 수집량을 결정한다.

| 소스 그룹 | 피드 수 | 건당 반환 | 수집량 | 중복 제거 후 |
|---------|--------|---------|-------|------------|
| 국내 증권 전문 RSS | 13개 | 20~100건 | ~650건 | ~280건 |
| 글로벌 investing.com RSS | 3개 | ~10건 | ~30건 | ~30건 |
| **합계** | **16개** | | **~680건** | **~310건/일** |

**성능 영향:**
- 수집량이 대폭 줄어 임베딩 API 비용 감소
- 고정 피드라 수집 구조 단순 — 스케줄러 1개로 전체 관리 가능
- pgvector HNSW 인덱스 필수 (클러스터링 성능)

---

## 2. 수집 대상 정의

### 2.1 수집 대상

16개 고정 RSS 피드(국내 증권 전문 13 + 글로벌 investing.com 3, → [4장](#4-수집-소스-검토))에서 들어오는 **증권·경제 뉴스 전체**를 수집한다. 키워드 검색이나 종목별 동적 수집을 하지 않으므로, 시장 이슈·개별 종목·산업 뉴스가 **구분 없이 섞여** 들어온다.

| 들어오는 뉴스 성격 | 예시 |
|------|------|
| 시장·거시 | "한국은행 기준금리 동결 결정" |
| 개별 기업·종목 | "삼성전자 3분기 영업이익 발표" |
| 산업·테마 | "AI 데이터센터 수요로 HBM 공급 부족" |

> 이 성격(시장/종목/산업)은 **수집 시점에 분류하지 않는다.** 고정 RSS에는 라벨이 없으므로, 유형 분류(L1)와 종목 식별(`company_tags`)은 **분석 단계**가 담당한다(→ [06](./06-news-analysis-design.md)).

### 2.2 수집 범위와 경계

| 항목 | 내용 |
|------|------|
| 범위 결정 방식 | **피드 선택**으로 결정 (키워드·종목 쿼리 없음) |
| 국내 | 국내 증권 전문 RSS 13개 (코스피·코스닥·기업·산업 뉴스 혼재) |
| 해외 | investing.com RSS 3개 (외환·해외 주식시장·경제지표) |
| 종목 커버리지 | 수집 단계에서 종목을 지정하지 않음 — 분석 단계 Entity NER가 본문에서 기업을 추출 (→ [5.2](#52-피드-운영-전략)) |
| 수집 안 함 | 본문·snippet·이미지 (저작권, → [3장](#3-저작권-및-법적-검토)) |

---

## 3. 저작권 및 법적 검토

### 3.1 서비스 성격 — 학습 서비스

장독대는 **주식 투자 추천·매매 신호를 제공하는 투자 서비스가 아니다.** 주린이(주식 초보자)가 뉴스와 시장 개념을 이해할 수 있도록 돕는 **주식 학습 플랫폼**이다.

이 구분은 뉴스 데이터 이용 약관 해석에 직접적인 영향을 준다.

| 구분 | 투자 서비스 | 장독대 (학습 서비스) |
|------|-----------|-------------------|
| 목적 | 매매 신호, 수익 추구 | 개념 학습, 뉴스 이해 |
| Naver API 약관 적용 | 상업적 이용 → 위반 가능 | 비상업적 학습 목적 → 허용 범위 |
| 유료화 시점 | — | 유료화·광고 수익화 시 재검토 필요 |

---

### 3.2 뉴스 저작권 기본 원칙

뉴스 기사는 저작권법상 저작물로 보호된다. 뉴스사의 기사 모음은 별도 데이터베이스권으로도 보호된다. 무단 크롤링 및 본문 복제·재배포는 저작권법 위반과 함께 컴퓨터 업무 방해죄에 해당할 수 있다.

크롤링의 합법성은 다음 기준으로 판단된다(대법원 판례 기준).

- robots.txt 준수 여부
- 서버에 과도한 부하를 주지 않을 것
- 상업적 무임승차 목적이 아닐 것
- 이용약관 위반이 없을 것

---

### 3.3 수집 방법별 리스크 등급

| 행위 | 리스크 | 근거 |
|------|--------|------|
| 공개 RSS 피드에서 제목·URL 수집 | **낮음** | 언론사가 공개 배포한 메타데이터 |
| RSS 피드 title·URL 저장 (snippet·본문 미저장) | **낮음** | 최소 메타데이터만 저장 |
| 분석 시점 본문 fetch 후 즉시 폐기 | **낮음** | 저장 없음 — 내부 처리 목적 |
| 뉴스 본문 전체를 DB에 저장 | **높음** | 저작물 무단 복제에 해당 |
| 언론사 웹사이트 직접 크롤링 (robots.txt 위반) | **높음** | 서버 부하 유발, 이용약관 위반 |

---

### 3.4 채택 전략 및 근거

**제목 + URL만 저장한다. snippet·본문은 DB에 저장하지 않는다.**

- 공개 RSS 피드에서 제목·URL만 수집해 저장권 리스크를 최소화한다.
- 본문이 필요한 경우(분석 시점) 대표 기사 URL로 실시간 fetch 후 사용하고 즉시 폐기한다.

---

## 4. 수집 소스 검토

### 4.1 후보 소스 전체 비교

| 소스 | 지역 | API 키 | 검토 결과 | 비고 |
|------|------|--------|----------|------|
| 국내 증권 전문 RSS 13개 | 국내 | 불필요 | ✅ **채택** | 증권 기사 밀도 높음 |
| investing.com RSS 3개 | 글로벌 | 불필요 | ✅ **채택** | 환율·지표·주식시장 커버 |
| Google News RSS | 국내+해외 | 불필요 | ❌ 제외 | 증권 특화 피드로 대체 |
| Finnhub API | 해외 | 필요 | ❌ 제외 | API 키 의존성 제거 |
| Naver News API | 국내 | 필요 | ❌ 제외 | API 키 의존성 제거 |
| BigKinds API | 국내 | 필요 | ❌ 제외 | 유료 전환됨 |

### 4.2 최종 선정 소스

#### 국내 증권 전문 RSS (고정 피드, 13개)

| 소스 | URL |
|------|-----|
| 한국경제 | `https://www.hankyung.com/feed/finance` |
| 매일경제 | `https://www.mk.co.kr/rss/50200011/` |
| 매일경제TV | `https://mbnmoney.mbn.co.kr/rss/news/stock` |
| 연합인포맥스 | `https://news.einfomax.co.kr/rss/S1N2.xml` |
| 더밸류뉴스 증권 | `https://www.thevaluenews.co.kr/rss_view.php?code=m6481nr` |
| 더밸류뉴스 기업분석 | `https://www.thevaluenews.co.kr/rss_view.php?code=m65gpg7` |
| 뉴스와이어 | `https://api.newswire.co.kr/rss/industry/203` |
| 아시아경제 | `https://view.asiae.co.kr/rss/stock.htm` |
| 서울경제 | `https://www.sedaily.com/rss/finance` |
| 뉴스토마토 | `https://www.newstomato.com/rss/?cate=12` |
| 이데일리 | `http://rss.edaily.co.kr/stock_news.xml` |
| 파이낸셜뉴스 | `https://www.fnnews.com/rss/r20/fn_realnews_stock.xml` |
| 뉴스핌 | `http://rss.newspim.com/news/category/105` |

#### 글로벌 경제 RSS (고정 피드, 3개)

| 소스 | URL | 용도 |
|------|-----|------|
| investing.com 외환 | `https://kr.investing.com/rss/news_1.rss` | 환율 뉴스 |
| investing.com 주식 | `https://kr.investing.com/rss/news_25.rss` | 해외 주식시장 |
| investing.com 경제지표 | `https://kr.investing.com/rss/news_95.rss` | PCE·고용 등 거시지표 |

---

## 5. 수집 방법

### 5.1 수집 방법

모든 소스가 RSS 피드이므로 `feedparser` 하나로 통일한다. API 키 불필요.

```python
import feedparser
import httpx

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    )
}

async def fetch_feed(client: httpx.AsyncClient, url: str) -> list[dict]:
    response = await client.get(url, timeout=10, headers=HEADERS)
    feed = feedparser.parse(response.text)
    return [
        {
            "title":      entry.get("title", ""),
            "url":        entry.get("link", ""),
            "source":     entry.get("source", {}).get("title", ""),
            "published":  entry.get("published", ""),
        }
        for entry in feed.entries
    ]

async def collect_all_feeds(feeds: list[str]) -> list[dict]:
    async with httpx.AsyncClient() as client:
        semaphore = asyncio.Semaphore(5)  # 동시 요청 제한
        async def fetch_with_sem(url):
            async with semaphore:
                return await fetch_feed(client, url)
        results = await asyncio.gather(*[fetch_with_sem(url) for url in feeds])
    return [item for batch in results for item in batch]
```

수집 데이터: 제목(`title`), URL(`url`), 출처(`source`), 발행일(`published`)

---

### 5.2 피드 운영 전략

키워드 검색 없이 **고정 피드를 주기적으로 폴링**한다. 종목 커버리지는 분석 단계의 Entity NER(`company_tags` 추출)이 담당한다.

```python
# 전체 피드를 한 번에 수집
ALL_FEEDS = DOMESTIC_SECURITIES_RSS + GLOBAL_INVESTING_RSS

async def run_collection() -> list[dict]:
    return await collect_all_feeds(ALL_FEEDS)
```

피드 추가·제거는 상수 목록만 수정하면 되므로 코드 변경 없이 운영 가능하다.

## 6. 주요 뉴스 선정 — 클러스터링 단계 담당

> **선정 로직은 수집 단계가 아니라 임베딩·클러스터링 단계(05)가 담당한다.**

"오늘 주목해야 할 뉴스"를 고르는 일은 **클러스터(같은 이슈로 묶인 기사 그룹)** 단위 평가이므로, 임베딩·클러스터링이 끝난 뒤에야 가능하다. 따라서 수집 단계(`NewsCollector`)는 **수집·저장만** 하고, 클러스터링·복합 중요도 스코어링·상위 이슈 선정은 `EmbeddingClusterer`가 수행한다.

| 관심사 | 담당 단계 | 문서 |
|--------|----------|------|
| 뉴스 수집·저장 | NewsCollector (수집) | 본 문서 [7장](#7-뉴스-수집-단계) |
| 클러스터링·복합 중요도 스코어·상위 이슈 선정 | EmbeddingClusterer (임베딩·클러스터링) | [05 §6](./05-embedding-clustering-design.md#6-주요-이슈-선정--복합-중요도-스코어) |

벤치마크(RUBICS·Bloomberg), 중요도 신호 5가지, 가중치 근거(휴리스틱·교정 대상)는 모두 [05 §6](./05-embedding-clustering-design.md#6-주요-이슈-선정--복합-중요도-스코어)을 단일 출처로 한다.

---

## 7. 뉴스 수집 단계

> 파이프라인 오케스트레이션 전체 설계는 [`01-pipeline-orchestration-design.md`](./01-pipeline-orchestration-design.md) 참조.

`NewsCollector`는 Airflow 메인 DAG가 09:00, 15:30에 실행하는 **수집 전용** 컴포넌트다. RSS 폴링·정규화·저장(`collect → save`)만 수행하고, 클러스터링·스코어링은 후속 단계([05 EmbeddingClusterer](./05-embedding-clustering-design.md#8-embeddingclusterer-설계))가 담당한다. `collect → save`는 분기·반복 없는 **정적 순차**이고 흐름 제어에 LLM 추론이 없으므로 실행 골격은 **Airflow Task**다(→ [00-workflow-airflow.md 5.2](./00-workflow-airflow.md#52-뉴스-수집-정적-순차--airflow-task로-교정)).

### 7.1 도구 (Tools)

| 도구 | 역할 |
|------|------|
| `rss_tool()` | feedparser로 **16개 고정 RSS 피드 폴링·정규화·URL 중복 제거** (키워드 검색 아님) |
| `save_tool(news_list)` | News 테이블 UPSERT (`ON CONFLICT(url) DO NOTHING`) |

> `cluster_tool`·`score_tool`은 수집 단계 도구가 아니다. 클러스터링·스코어링은 05 EmbeddingClusterer가 소유한다(→ [01 §4](./01-pipeline-orchestration-design.md#4-공유-도구-tools)).

### 7.2 처리 플로우 (정적 순차)

```python
class NewsCollectorState(TypedDict):
    schedule: str
    collected: int           # 수집한 원시 기사 수
    kept: int                # 전처리 통과(분석 대상) 수 — is_filtered=False
    saved: int               # upsert_news가 새로 삽입한 수
    failed_feeds: list[str]  # 수집 실패한 피드 식별자 (빈 리스트=전부 성공)

# collect → preprocess → save 정적 순차 (분기·반복 없음 → Airflow Task)
async def run(self, db, schedule: str) -> NewsCollectorState:
    collected, failed_feeds = await rss_collector.collect()  # 16개 고정 RSS 폴링·KST 정규화
    records, stats = run_preprocessing(              # HTML·URL·필터·제목중복 (인메모리, →04)
        [c.to_record() for c in collected]
    )
    saved = await upsert_news(db, records)           # 정제본 1회 저장 (ON CONFLICT url)
    return {"schedule": schedule, "collected": len(collected), "kept": stats.kept,
            "saved": saved, "failed_feeds": failed_feeds}
```

> **State는 데이터가 아니라 보고다.** 반환값은 Airflow Task 결과(XCom)이므로 수집 레코드 전체가 아니라 **카운트와 실패 신호**만 담는다. 실제 데이터 핸드오프는 공유 DB의 상태 컬럼(`is_filtered`/`embedding`)으로 이뤄지므로(→ [01 §2](./01-pipeline-orchestration-design.md#2-전체-구조--데이터-핸드오프)), 레코드를 XCom에 실으면 비대해지고 DB 핸드오프 원칙과 어긋난다. `failed_feeds`는 16개 중 일부가 조용히 실패해도 Task가 성공으로 끝나는 부분 실패를 단계 경계로 끌어올려, 수집량 급감을 로그가 아닌 구조적 신호로 인지하게 한다.

저장된 정제 뉴스(`is_filtered`로 분석 제외 표시)는 EmbeddingClusterer가 `is_filtered = FALSE AND embedding IS NULL`로 이어받는다(→ [01 §2](./01-pipeline-orchestration-design.md#2-전체-구조--데이터-핸드오프)). 전처리는 별도 단계가 아니라 수집 노드 안에서 인메모리로 처리된다(→ [04 §1.2](./04-preprocessing-design.md#12-전처리의-위치--수집전처리저장을-한-흐름으로)).


## 8. 데이터 명세


### 8.1 수집·저장 필드 정의

`news` 테이블 필드를 **채워지는 시점**으로 구분한다. 고정 RSS는 라벨이 없으므로 수집 시점 필드는 최소이고, 나머지는 각 파이프라인 단계가 채운다.

| 필드명 | 타입 | 채우는 시점 | 설명 |
|--------|------|------------|------|
| `title` | String(500) | **수집→전처리** | RSS 제목 (전처리에서 HTML 정제) |
| `url` | String(500), unique | **수집→전처리** | 원문 URL — 전처리에서 트래킹 파라미터 제거 후 저장 (중복 방지 키) |
| `source` | String(100) | **수집** | 피드 식별자 (예: `"hankyung"`, `"edaily"`, `"investing_stock"`) |
| `published_at` | DateTime, nullable | **수집** (KST 정규화) | 기사 발행 시각 (피드에 없으면 NULL) |
| `created_at` | DateTime | **저장** | DB 적재 시각 (server_default) |
| `is_filtered` | Boolean (기본 `False`) | **전처리** | 24h 초과·제목 중복으로 분석 제외 시 `True` |
| `is_duplicate` | Boolean (기본 `False`) | **임베딩(중복 제거)** | cosine ≥ 0.95 근접 중복 표시 — 삭제 대신 soft flag, 클러스터링·분석 제외 (→ [05 §4.2](./05-embedding-clustering-design.md#42-중복-제거-cosine--095--하드-삭제가-아니라-soft-flag)) |
| `embedding` | Vector(768), nullable | **임베딩** | title 임베딩 (pgvector) |
| `is_analyzed` | Boolean (기본 `False`) | **분석** | 분석 파이프라인 처리 여부 |

> `preprocessed_at` 컬럼은 인메모리 전처리 전환으로 **미사용**이며 모델에는 남아 있으나 마이그레이션으로 제거 예정이다(→ [04 §7](./04-preprocessing-design.md#7-db-변경-사항)). 위 표의 전체 스키마 정본은 ORM 모델 [`app/db/orm_models/news.py`](../../app/db/orm_models/news.py)이다(`rss_source`·`news_source`·`stock_code`·`score` 포함).

> **별도 테이블로 분리한 필드**:
> - **클러스터·스코어** — 클러스터는 기사당이 아니라 **기사 그룹당** 개념이고, 복합 중요도 스코어도 **클러스터당** 값이다. `news` 행에 두면 grain이 맞지 않으므로 [`news_cluster` 테이블](#83-news_cluster-테이블-클러스터링-산출물)로 분리한다. (구 `score`/`region` 컬럼 제거)
> - **유형·종목** — `source_type`(시장/종목)·`symbol`(종목 코드)은 고정 RSS에 라벨이 없어 수집 시점에 정할 수 없다. 분석 단계 산출물이며 [06](./06-news-analysis-design.md)의 `news_analysis`에서 관리한다.
>
> `region`(domestic/global)은 `source`(피드 식별자)로 항상 도출되므로 별도 컬럼을 두지 않는다.

**저장하지 않는 것**: snippet, 본문, 이미지, 기자명 — 저작권 리스크. 본문은 분석 시점에 대표 기사만 실시간 fetch 후 폐기(→ [8.4](#84-본문-fetch-전략)).

### 8.2 DB 스키마 (SQLAlchemy)

```python
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, UniqueConstraint
)
from pgvector.sqlalchemy import Vector
from app.db.database import Base


class News(Base):
    __tablename__ = "news"

    id               = Column(Integer, primary_key=True)
    title            = Column(String(500), nullable=False)
    url              = Column(String(500), nullable=False)
    source           = Column(String(100), nullable=False)   # 피드 식별자 (region 도출 가능)
    is_filtered      = Column(Boolean, default=False)         # 전처리에서 분석 제외 표시
    is_duplicate     = Column(Boolean, default=False)         # 임베딩 유사도(≥0.95) 근접 중복 — soft flag, 클러스터링·분석 제외 (삭제 아님 → 05 §4.2)
    # preprocessed_at: 인메모리 전처리 전환으로 미사용 — 마이그레이션으로 제거 예정 (→ 04 §7)
    embedding        = Column(Vector(768), nullable=True)                # title 임베딩
    is_analyzed      = Column(Boolean, default=False)
    published_at     = Column(DateTime(timezone=True), nullable=False)
    created_at       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    # 클러스터·복합 중요도 스코어는 grain이 달라 news_cluster로 분리 (→ 8.3)
    # source_type(시장/종목)·symbol(종목코드)은 분석 산출물(→ 06 news_analysis)
    # snippet, body 저장 안 함 — 저작권 리스크. 본문은 분석 시점에 실시간 fetch 후 폐기

    __table_args__ = (UniqueConstraint("url"),)
```

#### 필수 인덱스

```sql
-- 중복 방지 (UniqueConstraint와 동일, 명시적 선언)
CREATE UNIQUE INDEX idx_news_url ON news (url);

-- 미처리 뉴스 조회 최적화 (분석 파이프라인이 자주 호출)
CREATE INDEX idx_news_unanalyzed ON news (is_analyzed, published_at DESC)
    WHERE is_analyzed = FALSE;

-- pgvector HNSW 인덱스 — 클러스터링·유사도 검색 성능 핵심
-- 인덱스 없으면 누적 벡터 수에 비례해 전체 스캔 발생
CREATE INDEX idx_news_embedding ON news USING hnsw (embedding vector_cosine_ops);
```

> HNSW 인덱스는 pgvector 활성화 직후 생성한다. 벡터가 수십만 건 쌓인 뒤 추가하면 인덱스 빌드 시간이 오래 걸린다.

### 8.3 `news_cluster` 테이블 (클러스터링 산출물)

클러스터링·스코어링은 [05 EmbeddingClusterer](./05-embedding-clustering-design.md#8-embeddingclusterer-설계)가 수행하며, 그 결과를 `news_cluster`에 적재한다. `news`(기사당)와 grain이 다른 **클러스터당 1행**이다. `embedding`은 `news`에 남고, 클러스터 식별·소속·스코어만 분리한다.

```python
from sqlalchemy import ARRAY, Date, Float, ForeignKey

class NewsCluster(Base):
    __tablename__ = "news_cluster"

    id                     = Column(Integer, primary_key=True)
    run_date               = Column(Date, nullable=False)             # 클러스터링 실행 일자
    representative_news_id  = Column(Integer, ForeignKey("news.id"), nullable=False)  # 대표 기사 = member_news_ids[0]
    member_news_ids        = Column(ARRAY(Integer), nullable=False)   # 소속 기사 id (중심 근접순 정렬 — fetch fallback 순서, → 05 §5.8)
    size                   = Column(Integer, nullable=False)          # 클러스터 기사 수
    importance             = Column(Float, nullable=False)            # 복합 중요도 스코어 [0,1]
    created_at             = Column(DateTime(timezone=True),
                                    default=lambda: datetime.now(timezone.utc))
```

> 스키마·스코어 산식의 단일 출처는 [05 §6](./05-embedding-clustering-design.md#6-주요-이슈-선정--복합-중요도-스코어)이다. 분석 단계는 `news_cluster`를 `importance` 내림차순으로 읽어 상위 이슈를 인계받는다(→ [06](./06-news-analysis-design.md)).

### 8.4 본문 fetch 전략

snippet은 저장하지 않는다. 분석 시점에 클러스터 대표 기사 URL로 **trafilatura**를 통해 본문을 실시간 fetch하고 사용 후 폐기한다.

| 상황 | 대응 |
|------|------|
| 정상 fetch | 대표기사(`member_news_ids[0]`) 본문을 LLM 입력으로 사용 후 폐기 |
| 페이월 | `member_news_ids` 중심 근접순(→ 05 §5.8)으로 다음 후보 순차 시도 |
| 전부 실패 | title만으로 분석 (품질 저하 허용)

---

## 9. 수집 주기

한국 주식 시장 운영 시간(09:00~15:20)을 기준으로 하루 2회 수집한다.

| 시점 | 수집 내용 | 이유 |
|------|----------|------|
| **09:00** | 전일 야간 뉴스 + 당일 프리마켓 뉴스 | 장 시작 전 이슈 파악 |
| **15:30** | 당일 장 중 뉴스 전체 + 분석 파이프라인 트리거 | 장 마감(15:20) 직후 당일 전체 분석 |

스케줄링은 **Airflow DAG**가 담당한다. 상세 DAG 정의는 [`01-pipeline-orchestration-design.md`](./01-pipeline-orchestration-design.md) 섹션 3.3 참조.

```python
# dags/jangdokdae_morning.py — Airflow cron 예시
schedule_interval="0 9 * * 1-5"   # 평일 09:00 KST
schedule_interval="30 15 * * 1-5"  # 평일 15:30 KST
```

---

## 10. 시스템 아키텍처

### 10.1 전체 파이프라인 구조

수집·전처리·임베딩을 각각 독립된 단계(컴포넌트)로 분리하고, **Airflow DAG**가 전체를 조율한다(스케줄·의존성·재시도). 전체 데이터 흐름·단계 인덱스·디렉토리 구조는 [01 통합 개요](./01-pipeline-orchestration-design.md), DAG·스케줄은 [00](./00-workflow-airflow.md)을 단일 출처로 한다.

뉴스 수집 단계가 닿는 파일:
- `services/pipeline/news_collector.py` — 단계 진입점 (`collect→save`)
- `services/collector/rss_collector.py` + `tools/`(rss·save) — 수집·도구
- `services/preprocessor/`, `services/embedder/` — 후속 단계가 소비 (클러스터링·스코어링 포함)

---

### 10.2 오케스트레이션 (Airflow DAG)

단계들의 **실행 순서·타이밍·의존성·재시도**는 Airflow DAG가 관리한다(별도 MasterOrchestrator 객체 없음). 각 Task가 해당 단계를 직접 호출하며, 단계끼리 직접 통신하지 않는다 — **공유 DB를 통해 데이터를 전달**한다. 상세는 [00-workflow-airflow.md](./00-workflow-airflow.md) 참조.

**단계 간 의존성:**

```
NewsCollector(수집→전처리) ─┐
                            ├→ DB 저장 (정제본, is_filtered) → EmbeddingClusterer
CompanyCollector           ─┘                                  ↓
                                                          analyze (L2 → 06 §18)
```

> Airflow 없이 전체를 로컬에서 한 번에 돌리려면 `services/pipeline/runner.py`의 `run_pipeline()`을 쓴다(하이브리드).

---

### 10.3 단계 상세 설계 참조

각 단계의 상태, 노드, 플로우, 에러 처리는 별도 문서를 참조한다.

→ [`01-pipeline-orchestration-design.md`](./01-pipeline-orchestration-design.md)


## 11. 구현 로드맵

단계별로 독립 구현 후 **Airflow DAG**로 통합한다.

### Phase 1 — 수집기 도구 구현

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 1 | `RssCollector` 구현 (국내 증권 13개 + investing.com 3개) | `services/collector/rss_collector.py` |
| 2 | `normalizer.py` 구현 | `services/preprocessor/normalizer.py` |
| 3 | `rss_tool`, `save_tool` 구현 | `services/collector/tools/` |
| 4 | DB 스키마 반영 (`News`) | `app/db/models.py` |

### Phase 2 — NewsCollector(수집 전용) 구현

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 5 | DB 스키마 마이그레이션 (`News`, `news_cluster`) + pgvector 활성화 | Alembic / DB |
| 6 | `NewsCollector` 정적 순차(collect→save) 구현 | `services/pipeline/news_collector.py` |

> 클러스터링·스코어링(`cluster.py`·`news_embedder.py`·`news_cluster` 적재)은 수집 단계가 아니라 **임베딩·클러스터링 단계**가 담당한다 → [05 구현 로드맵](./05-embedding-clustering-design.md#10-구현-로드맵).

### Phase 3 — 전처리 모듈

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 7 | `deduplicator.py`, `filter.py` 구현 | `services/preprocessor/` |
| 8 | `Preprocessor` 구현 | `services/pipeline/preprocessor.py` |

### Phase 4 — Airflow 통합

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 9 | `run_pipeline()` 러너 구현 (하이브리드 로컬 실행) | `services/pipeline/runner.py` |
| 10 | Airflow DAG 작성 (메인 09:00·15:30 + 보조) | `dags/jangdokdae_pipeline.py` 등 |

### Phase 5 — 본문 fetch 품질 검증

| 조건 | 대응 방안 |
|------|----------|
| trafilatura fetch 성공률 충분 | 현행 유지 |
| 페이월 비율 높음 | 관련 기사 fallback 로직 강화 |


## 12. 미결 사항

| 항목 | 내용 | 결정 시점 |
|------|------|----------|
| 임베딩 모델 선정 | ✅ **확정 — `gemini-embedding-001`(768)** (3축 평가 세 축 모두 1위 → [평가 보고서](../evaluation/00-embedding-model-evaluation.md), 정본 [05 §2.1](./05-embedding-clustering-design.md#21-임베딩-모델-비교)) | 완료(2026-06-09) |
| 클러스터링 임계값 | 실제 뉴스 100건으로 교정 테스트 후 결정 | Phase 2 구현 후 |
| 본문 fetch 품질 | trafilatura 성공률 및 페이월 비율 검증 | Phase 1 구현 후 테스트 |
| 관심 종목 없는 초기 사용자 대응 | 기본 피드 뉴스만 제공할지 여부 | 기획 논의 필요 |

---

## 참고 자료

- [Neon pgvector 공식 문서](https://neon.com/docs/extensions/pgvector)
- [디지털 뉴스콘텐츠 이용규칙 (한국언론진흥재단)](https://www.kpf.or.kr/front/board/boardContentsView.do?board_id=291&contents_id=855b0c963b5c4a42ba6b26d06c7186d4)
- [웹크롤링 법적 판단 기준 — 대법원 2021도1533](https://atlaw.kr/kr-blog/%EC%9B%B9%ED%81%AC%EB%A1%A4%EB%A7%81%EC%9D%98-%ED%98%95%EC%82%AC%EC%B2%98%EB%B2%8C-%EA%B0%80%EB%8A%A5%EC%84%B1-%EB%8C%80%EB%B2%95%EC%9B%90-2021%EB%8F%841533-%ED%8C%90%EA%B2%B0-%EC%99%84%EC%A0%84/)
