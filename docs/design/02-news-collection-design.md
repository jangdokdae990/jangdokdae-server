# 뉴스 데이터 수집 기획서

**작성일** 2026-05-28  
**기획 범위** 뉴스 수집 → 전처리 → 임베딩  
**관련 문서**  
- [에이전트 오케스트레이션 아키텍처](./01-agent-orchestration-design.md)
- [전처리 기획서](./04-preprocessing-design.md)

---

## 목차

- [1. 개요](#1-개요)
- [2. 수집 대상 정의](#2-수집-대상-정의)
- [3. 저작권 및 법적 검토](#3-저작권-및-법적-검토)
- [4. 수집 소스 검토](#4-수집-소스-검토)
- [5. 수집 방법](#5-수집-방법)
- [6. 주요 뉴스 선정 방법론](#6-주요-뉴스-선정-방법론)
- [7. 뉴스 수집 에이전트](#7-뉴스-수집-에이전트)
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

### 2.1 뉴스 유형 분류

| 유형 | 설명 | 예시 |
|------|------|------|
| **시장 뉴스** | 코스피·코스닥·금리·환율 등 거시 경제 이슈 | "한국은행 기준금리 동결 결정" |
| **종목 뉴스** | 특정 기업·산업 관련 뉴스 | "삼성전자 3분기 영업이익 발표" |

### 2.2 수집 범위

```
국내
  시장 뉴스  →  코스피, 코스닥, 금리, 환율, 반도체, 2차전지 등 키워드
  종목 뉴스  →  사용자 관심 종목 기반 동적 수집

해외
  시장 뉴스  →  Fed, S&P500, NASDAQ, 유가 등 글로벌 거시 키워드
  종목 뉴스  →  관심 해외 종목 ticker 기반 수집
```

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

## 6. 주요 뉴스 선정 방법론

수집한 뉴스 전체를 분석 파이프라인에 넘기는 것은 비효율적이다. **"오늘 주목해야 할 뉴스"를 어떻게 선정할 것인가**는 서비스 품질을 결정하는 핵심 문제다.

### 6.1 타 서비스 벤치마크

#### 카카오 루빅스 (RUBICS)

카카오가 2015년 도입한 실시간 뉴스 추천 시스템. 가장 참고할 만한 국내 사례다.

> **핵심 로직**: "1시간 동안 같은 이슈로 묶인 기사 수가 많은 이슈를 주요 이슈로 선정한다"

기자들이 많이 쓴 주제 = 세상이 주목하는 이슈라는 논리다.

```
수집 → 클러스터링(유사 기사 묶기) → 클러스터 크기(기사 수) → 상위 6개 = 오늘의 주요 이슈
```

추가로 **실시간 사용자 반응**(클릭률, 체류 시간)을 반영해 순위를 조정한다. 또한 어뷰징(동일 기사 반복 송고) 필터링으로 인위적 볼륨 증폭을 차단한다.

---

#### Bloomberg Terminal

금융 전문 단말기. 알고리즘과 편집자를 함께 사용한다.

| 기능 | 방식 |
|------|------|
| **Top News** | 편집자가 직접 선별한 하루 핵심 뉴스 |
| **First Word** | 속보를 bullet point로 즉시 요약 |
| **감성 점수** | 뉴스별 긍정/부정 수치 제공 |
| **AI 3줄 요약** | 중요 기사를 자동으로 3문장 요약 |

블룸버그는 **속도(velocity)** 를 핵심 신호로 쓴다. 같은 종목에 기사가 갑자기 쏟아지면 상단에 노출된다.

---

#### 학술 연구 기반 — 중요도 신호 5가지

금융 뉴스 중요도 연구에서 공통적으로 등장하는 신호:

| 신호 | 정의 | 측정 방법 |
|------|------|----------|
| **Volume** | 같은 이슈 기사 수 | 클러스터 내 기사 수 |
| **Velocity** | 기사 발행 속도 | 단위 시간(1h)당 급증률 |
| **Sentiment** | 긍정/부정 강도 | FinBERT 감성 점수 |
| **Entity Prominence** | 언급된 기업 중요도 | 코스피200 여부, 시총 |
| **Social Signals** | SNS·검색 반응 | 구글 트렌드, 트위터 멘션 수 |

장독대 MVP에서는 **Volume + Velocity** 3가지로 시작하고, 이후 Sentiment·Entity Prominence를 추가한다.

---

### 6.2 장독대 주요 뉴스 선정 로직

벤치마크 조사를 바탕으로 3단계 선정 로직을 채택한다.

```
[1단계] 볼륨 스코어링
  수집된 뉴스를 클러스터링 → 클러스터 크기(기사 수) = 이슈 볼륨 점수
  → 볼륨이 높을수록 많은 기자가 주목한 이슈

[2단계] 속도 스코어링
  이전 수집 대비 클러스터 증가율 계산
  → 급격히 커지는 클러스터 = 지금 터지고 있는 이슈

[3단계] LLM 최종 판단
  상위 클러스터를 FilterChain에 통과
  → "주린이에게 중요한가?" 최종 판단
  → 통과한 클러스터 = Issue Docent 생성 대상
```

```python
def score_cluster(cluster: list[News], prev_cluster_size: int) -> float:
    volume_score   = len(cluster)                              # 기사 수
    velocity_score = len(cluster) - prev_cluster_size          # 증가 속도
    return volume_score * 0.6 + velocity_score * 0.4
```

---

## 7. 뉴스 수집 에이전트

> 에이전트 오케스트레이션 전체 설계는 [`01-agent-orchestration-design.md`](./01-agent-orchestration-design.md) 참조.

`NewsCollectionAgent`는 `MasterOrchestrator`가 09:00, 15:30에 실행하는 LangGraph 기반 에이전트다.

### 7.1 에이전트 도구 (Tools)

| 도구 | 역할 |
|------|------|
| `search_tool(keyword, region)` | Google RSS / Naver / Finnhub 검색 |
| `cluster_tool(news_list)` | pgvector cosine similarity로 이슈 클러스터링 |
| `score_tool(clusters)` | 볼륨(기사 수) + 속도(증가율) 점수 계산 |
| `save_tool(news_list)` | News 테이블 UPSERT |

### 7.2 에이전트 플로우 (LangGraph)

```python
class NewsAgentState(TypedDict):
    schedule: str
    keywords: list[str]
    collected: list[dict]
    clusters: list[dict]
    scored: list[dict]
    top_issues: list[dict]
    errors: list[str]

workflow = StateGraph(NewsAgentState)
workflow.add_node("collect",  collect_node)
workflow.add_node("cluster",  cluster_node)
workflow.add_node("score",    score_node)
workflow.add_node("finalize", finalize_node)

workflow.set_entry_point("collect")
workflow.add_edge("collect",  "cluster")
workflow.add_edge("cluster",  "score")
workflow.add_edge("score",    "finalize")
workflow.add_edge("finalize", END)
```


## 8. 데이터 명세


### 8.1 수집·저장 필드 정의

| 필드명 | 타입 | 출처 | 설명 |
|--------|------|------|------|
| `title` | String(500) | 모든 소스 | 뉴스 제목 |
| `url` | String(500) | 모든 소스 | 원문 URL. **unique 제약으로 중복 방지** |
| `source` | String(100) | — | 소스 식별자 (예: `"hankyung"`, `"edaily"`, `"investing_stock"`) |
| `source_type` | String(50) | — | 뉴스 유형 (`"market_news"` / `"stock_news"`) |
| `region` | String(10) | — | 지역 (`"domestic"` / `"global"`) |
| `symbol` | String(20) | — | 종목 코드. 종목 뉴스만 값 있음 |
| `preprocessed_at` | DateTime(tz) | — | NULL=미처리. PreprocessingAgent 완료 시각 기록 |
| `is_analyzed` | Boolean | — | 분석 파이프라인 처리 여부. 기본값 `False` |
| `published_at` | DateTime | 모든 소스 | 기사 발행 시각 |
| `score` | Float | 임베딩 단계 | 볼륨·속도 스코어 (클러스터 대표 기사 선정에 사용) |
| `embedding` | Vector(768) | 임베딩 단계 | title 임베딩. pgvector 저장 |

**저장하지 않는 것**: snippet, 본문, 이미지, 기자명  
→ snippet·본문은 저작권 리스크. 본문은 분석 시점에 대표 기사만 실시간 fetch 후 폐기.

### 8.2 DB 스키마 (SQLAlchemy)

```python
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, UniqueConstraint
)
from pgvector.sqlalchemy import Vector
from app.db.database import Base


class News(Base):
    __tablename__ = "news"

    id               = Column(Integer, primary_key=True)
    title            = Column(String(500), nullable=False)
    url              = Column(String(500), nullable=False)
    source           = Column(String(100), nullable=False)
    source_type      = Column(String(50), nullable=False)
    region           = Column(String(10), nullable=False)
    symbol           = Column(String(20), nullable=True)
    preprocessed_at  = Column(DateTime(timezone=True), nullable=True)   # NULL=미처리
    is_analyzed      = Column(Boolean, default=False)
    published_at     = Column(DateTime(timezone=True), nullable=False)
    created_at       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    score            = Column(Float, nullable=True)                      # 볼륨·속도 스코어
    embedding        = Column(Vector(768), nullable=True)                # title 임베딩
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

### 8.3 본문 fetch 전략

snippet은 저장하지 않는다. 분석 시점에 클러스터 대표 기사 URL로 **trafilatura**를 통해 본문을 실시간 fetch하고 사용 후 폐기한다.

| 상황 | 대응 |
|------|------|
| 정상 fetch | 본문을 LLM 입력으로 사용 후 폐기 |
| 페이월 | 관련 기사 목록에서 대체 기사 순차 시도 |
| 전부 실패 | title만으로 분석 (품질 저하 허용)

---

## 9. 수집 주기

한국 주식 시장 운영 시간(09:00~15:20)을 기준으로 하루 2회 수집한다.

| 시점 | 수집 내용 | 이유 |
|------|----------|------|
| **09:00** | 전일 야간 뉴스 + 당일 프리마켓 뉴스 | 장 시작 전 이슈 파악 |
| **15:30** | 당일 장 중 뉴스 전체 + 분석 파이프라인 트리거 | 장 마감(15:20) 직후 당일 전체 분석 |

스케줄링은 **Airflow DAG**가 담당한다. 상세 DAG 정의는 [`01-agent-orchestration-design.md`](./01-agent-orchestration-design.md) 섹션 3.3 참조.

```python
# dags/jangdokdae_morning.py — Airflow cron 예시
schedule_interval="0 9 * * 1-5"   # 평일 09:00 KST
schedule_interval="30 15 * * 1-5"  # 평일 15:30 KST
```

---

## 10. 시스템 아키텍처

### 10.1 전체 멀티 에이전트 구조

수집·전처리·임베딩을 각각 독립된 에이전트로 분리하고, `MasterOrchestrator`가 전체를 조율한다.

```
dags/                              ← Airflow DAG (스케줄링 담당)
  ├── jangdokdae_morning.py      ← 09:00 평일
  ├── jangdokdae_afternoon.py    ← 15:30 평일
  └── jangdokdae_market_close.py ← 16:30 평일

services/
  ├── master_orchestrator.py              ← MasterOrchestrator  ⭐ 전체 조율
  │
  ├── agents/
  │   ├── news_collection_agent.py        ← NewsCollectionAgent (LangGraph)
  │   ├── company_collection_agent.py     ← CompanyCollectionAgent (LangGraph)
  │   ├── preprocessing_agent.py        ← PreprocessingAgent
  │   └── embedding_clustering_agent.py   ← EmbeddingClusteringAgent
  │
  ├── collector/               ← 수집기 (에이전트 도구로 사용)
  │   ├── tools/
  │   │   ├── search_tool.py   ← Google RSS (topic + search) / Finnhub 검색
  │   │   ├── dart_tool.py     ← DART 공시 수집
  │   │   ├── stock_tool.py    ← 주가 수집 (FinanceDataReader)
  │   │   ├── macro_tool.py    ← 환율·금리 수집
  │   │   ├── cluster_tool.py  ← 클러스터링 + 볼륨 스코어
  │   │   └── save_tool.py     ← DB UPSERT
  │   └── rss_collector.py          ← 국내 증권 RSS + investing.com 통합
  │
  ├── preprocessor/            ← 전처리기 (PreprocessingAgent 도구)
  │   ├── deduplicator.py
  │   ├── filter.py
  │   └── normalizer.py
  │
  └── embedder/                ← 임베더 (EmbeddingClusteringAgent 도구로 사용)
      ├── news_embedder.py
      └── cluster.py
```

---

### 10.2 MasterOrchestrator 역할

에이전트들의 **실행 순서·타이밍·의존성**을 관리한다.  
에이전트끼리 직접 통신하지 않는다. **공유 DB를 통해 데이터를 전달**한다.

```python
class MasterOrchestrator:
    async def run_morning(self) -> None:
        """09:00 — 장 시작 전"""
        await asyncio.gather(
            self.news_agent.run("morning"),
            self.company_agent.run("morning"),
        )
        # 전처리는 수집 인라인 실행 (04-preprocessing-design.md 참조)
        await self.embedding_agent.run()

    async def run_afternoon(self) -> None:
        """15:30 — 장 마감 직후"""
        await asyncio.gather(
            self.news_agent.run("afternoon"),
            self.company_agent.run("afternoon"),
        )
        # 전처리는 수집 인라인 실행 (04-preprocessing-design.md 참조)
        await self.embedding_agent.run()
        await self._trigger_analysis_pipeline()

    async def run_market_close(self) -> None:
        """16:30 — 주가·거시지표 수집 (전처리·임베딩 불필요)"""
        await self.company_agent.run("market_close")
```

**에이전트 간 의존성:**

```
NewsCollectionAgent   ─┐
                        ├→ DB 저장 (원시, preprocessed_at=NULL) → PreprocessingAgent → EmbeddingClusteringAgent
CompanyCollectionAgent ─┘                                        ↓
                                                       분석 파이프라인 트리거
```

---

### 10.3 에이전트 상세 설계 참조

각 에이전트의 상태, 노드, 플로우, 에러 처리는 별도 문서를 참조한다.

→ [`01-agent-orchestration-design.md`](./01-agent-orchestration-design.md)


## 11. 구현 로드맵

에이전트별로 독립 구현 후 `MasterOrchestrator`로 통합한다.

### Phase 1 — 수집기 도구 구현

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 1 | `RssCollector` 구현 (국내 증권 13개 + investing.com 3개) | `services/collector/rss_collector.py` |
| 2 | `normalizer.py` 구현 | `services/preprocessor/normalizer.py` |
| 3 | `search_tool`, `save_tool` 구현 | `services/collector/tools/` |
| 4 | DB 스키마 반영 (`News`) | `app/db/models.py` |

### Phase 2 — NewsCollectionAgent 구현

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 8 | pgvector 활성화 | DB 마이그레이션 |
| 9 | `news_embedder.py`, `cluster.py` 구현 | `services/embedder/` |
| 10 | `cluster_tool`, `score_tool` 구현 | `services/collector/tools/` |
| 11 | `NewsCollectionAgent` LangGraph 노드 구현 | `services/agents/news_collection_agent.py` |

### Phase 3 — 전처리 모듈 + EmbeddingClusteringAgent 구현

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 13 | `deduplicator.py`, `filter.py` 구현 | `services/preprocessor/` |
| 14 | `PreprocessingAgent` 구현 | `services/agents/preprocessing_agent.py` |
| 15 | `EmbeddingClusteringAgent` 구현 | `services/agents/embedding_clustering_agent.py` |

### Phase 4 — MasterOrchestrator 통합

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 16 | `MasterOrchestrator` 구현 | `services/master_orchestrator.py` |
| 17 | Airflow DAG 작성 (09:00 / 15:30 / 16:30) | `dags/` |
| 18 | 키워드 통과율 집계 | `app/db/queries.py` |

### Phase 5 — 본문 fetch 품질 검증

| 조건 | 대응 방안 |
|------|----------|
| trafilatura fetch 성공률 충분 | 현행 유지 |
| 페이월 비율 높음 | 관련 기사 fallback 로직 강화 |


## 12. 미결 사항

| 항목 | 내용 | 결정 시점 |
|------|------|----------|
| 임베딩 모델 선정 | `text-multilingual-embedding-002` 1순위 후보, 확정 필요 | Phase 2 시작 전 |
| 클러스터링 임계값 | 실제 뉴스 100건으로 교정 테스트 후 결정 | Phase 2 구현 후 |
| 본문 fetch 품질 | trafilatura 성공률 및 페이월 비율 검증 | Phase 1 구현 후 테스트 |
| 관심 종목 없는 초기 사용자 대응 | 기본 피드 뉴스만 제공할지 여부 | 기획 논의 필요 |

---

## 참고 자료

- [Neon pgvector 공식 문서](https://neon.com/docs/extensions/pgvector)
- [디지털 뉴스콘텐츠 이용규칙 (한국언론진흥재단)](https://www.kpf.or.kr/front/board/boardContentsView.do?board_id=291&contents_id=855b0c963b5c4a42ba6b26d06c7186d4)
- [웹크롤링 법적 판단 기준 — 대법원 2021도1533](https://atlaw.kr/kr-blog/%EC%9B%B9%ED%81%AC%EB%A1%A4%EB%A7%81%EC%9D%98-%ED%98%95%EC%82%AC%EC%B2%98%EB%B2%8C-%EA%B0%80%EB%8A%A5%EC%84%B1-%EB%8C%80%EB%B2%95%EC%9B%90-2021%EB%8F%841533-%ED%8C%90%EA%B2%B0-%EC%99%84%EC%A0%84/)
