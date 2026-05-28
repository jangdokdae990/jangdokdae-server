# 전처리 기획서

**작성일** 2026-05-28  
**기획 범위** 수집 완료 → 전처리 → 임베딩 파이프라인 인계  
**관련 문서**  
- [에이전트 오케스트레이션 아키텍처](./01-agent-orchestration-design.md)
- [뉴스 데이터 수집 기획서](./02-news-collection-design.md)
- [기업 데이터 수집 기획서](./03-company-data-collection-design.md)

---

## 목차

- [1. 목적](#1-목적)
- [2. 전처리 파이프라인](#2-전처리-파이프라인)
- [3. 단계별 상세](#3-단계별-상세)
- [4. 전처리 모듈 설계](#4-전처리-모듈-설계)
- [5. 소스별 전처리 적용 매트릭스](#5-소스별-전처리-적용-매트릭스)
- [6. 에러 처리](#6-에러-처리)
- [7. DB 변경 사항](#7-db-변경-사항)
- [8. 구현 로드맵](#8-구현-로드맵)
- [참고 자료](#참고-자료)

---

## 1. 목적

### 1.1 전처리가 필요한 이유

수집 단계에서 저장된 데이터는 소스마다 형식이 다르고 품질이 불균일하다.  
전처리 없이 임베딩·LLM 분석에 넘기면 다음 문제가 발생한다.

| 문제 | 원인 | 영향 |
|------|------|------|
| HTML 태그 포함 | Naver API `description` 필드 | 임베딩 품질 저하, LLM 혼란 |
| 타임존 불일치 | 소스별 UTC/KST/Unix 혼용 | 날짜 필터·정렬 오류 |
| 리다이렉트 URL | Google RSS `entry.link` | URL unique 제약 무효화 |
| 중복 기사 | 동일 이슈를 여러 소스가 동시 보도 | 임베딩 비용 낭비, 클러스터 왜곡 |
| 오래된 기사 | RSS 피드에 과거 기사 포함 | 분석 파이프라인에 stale 데이터 투입 |

### 1.2 전처리의 위치

전처리는 **별도 `PreprocessingAgent`가 수집 완료 후 실행**한다.  
수집 에이전트는 원시 데이터를 저장하고, PreprocessingAgent가 이를 정제한다.

```
[수집] → DB 저장 (원시 데이터, preprocessed_at=NULL)
                    ↓
         [PreprocessingAgent] ← preprocessed_at IS NULL 조회
                    ↓
         DB 업데이트 (정제 완료, preprocessed_at=timestamp)
                    ↓
         [임베딩·클러스터링] ← preprocessed_at IS NOT NULL AND embedding IS NULL
                    ↓
              [분석 파이프라인]
```

**`preprocessed_at` 타임스탬프**로 상태를 추적한다.  
- `NULL` → 미처리  
- 값 있음 → 처리 완료 (언제 처리됐는지 이력 보존)  
임베딩 에이전트는 `preprocessed_at IS NOT NULL AND embedding IS NULL` 조건으로 조회해  
전처리 완료된 레코드만 임베딩한다.

### 1.3 처리 대상

- **뉴스** (`news` 테이블): 소스별로 HTML·타임존·URL 정규화 필요
- **공시** (`disclosures` 테이블): DART 공공 데이터, HTML·타임존 이슈 없음 → 전처리 불필요

---

## 2. 전처리 파이프라인

총 5단계. 순서가 중요하다 — HTML 제거 후 URL 정규화, 정규화 후 필터링, 필터링 후 중복 제거 순서로 진행한다.

```
[DB] preprocessed_at IS NULL 레코드 조회 (배치)
    │
    ▼
Step 1. HTML 정제
    │    Naver description의 <b> 태그·HTML 엔티티 제거
    ▼
Step 2. 타임존 정규화
    │    모든 published_at → UTC aware datetime
    ▼
Step 3. URL 정규화
    │    3-A. Google RSS 리다이렉트 → 실제 기사 URL
    │    3-B. utm_source, fbclid 등 트래킹 파라미터 제거
    ▼
Step 4. 필터링
    │    4-A. 날짜 필터 (24시간 초과 제거)
    │    4-B. snippet 최소 길이 필터 (20자 미만 제거)
    ▼
Step 5. 중복 제거
    │    5-A. DB 레벨 URL unique 제약 (수집 시점 처리)
    │    5-B. 제목 텍스트 유사도 중복 제거 (배치 내 처리)  ← 신규
    │    5-C. 벡터 유사도 중복 제거 (EmbeddingClusteringAgent 담당)
    │
    ▼
DB 업데이트 (preprocessed_at=now(), url 정규화 반영)
```

---

## 3. 단계별 상세

### Step 1. HTML 정제

**대상 소스**: Naver News API (`description` 필드)  
**문제**: 검색어 강조를 위한 `<b>` 태그와 HTML 엔티티(`&amp;`, `&lt;` 등) 포함

```
입력:  "<b>삼성전자</b> 3분기 영업이익이 &amp;전년 대비..."
출력:  "삼성전자 3분기 영업이익이 &전년 대비..."
```

```python
import html
from bs4 import BeautifulSoup

def clean_html(text: str) -> str:
    if not text:
        return ""
    text = html.unescape(text)                               # &amp; → &
    text = BeautifulSoup(text, "html.parser").get_text()     # <b> 제거
    return text.strip()
```

**소스별 적용 여부:**

| 소스 | HTML 정제 필요 |
|------|--------------|
| Naver API | ✅ 필요 |
| Google News RSS | 불필요 (plain text) |
| Finnhub | 불필요 (plain text) |

---

### Step 2. 타임존 정규화

**문제**: 소스마다 시간 형식이 다르다.

| 소스 | 형식 | 예시 |
|------|------|------|
| Google News RSS | RFC 2822 (KST 포함) | `"Thu, 28 May 2026 09:00:00 +0900"` |
| Naver API | RFC 2822 (KST) | `"Thu, 28 May 2026 09:00:00 +0900"` |
| Finnhub | Unix timestamp (UTC) | `1748390400` |

**모든 `published_at`을 UTC aware datetime으로 정규화한다.**

```python
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

def normalize_published_at(raw, source: str) -> datetime:
    if source == "finnhub":
        return datetime.fromtimestamp(int(raw), tz=timezone.utc)
    else:
        # Google RSS, Naver — RFC 2822 파싱 후 UTC 변환
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
```

---

### Step 3. URL 정규화

#### 3-A. Google RSS 리다이렉트 해소

**문제**: Google News RSS의 `entry.link`는 실제 기사 URL이 아닌 구글 리다이렉트 URL이다.

```
입력:  "https://news.google.com/rss/articles/CBMiXGh0dHBzOi8..."
출력:  "https://www.hankyung.com/article/2026052812345"
```

리다이렉트 URL이 그대로 저장되면:
- 같은 기사가 다른 Google URL로 중복 수집될 수 있음
- 시간이 지나면 Google URL이 만료되어 접근 불가

```python
import httpx

async def resolve_google_rss_url(url: str) -> str:
    if "news.google.com" not in url:
        return url
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=5.0) as client:
            response = await client.head(url)
            return str(response.url)
    except Exception:
        return url  # 실패 시 원본 URL 유지
```

> **성능**: HTTP 요청이 필요하므로 배치 내 최대 50건 병렬 처리.

---

#### 3-B. 트래킹 파라미터 제거

**문제**: 동일 기사 URL에 추적 파라미터가 붙어 다른 URL로 인식된다.

```
같은 기사:
  https://hankyung.com/article/123?utm_source=naver&utm_medium=news
  https://hankyung.com/article/123?fbclid=abc123
  https://hankyung.com/article/123
```

URL unique 제약만으로는 같은 기사로 인식되지 않으므로, 저장 전에 트래킹 파라미터를 제거한다.

```python
from urllib.parse import urlparse, urlencode, parse_qs

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid", "gclid", "ref", "source",
}

def remove_tracking_params(url: str) -> str:
    parsed = urlparse(url)
    clean_params = {
        k: v for k, v in parse_qs(parsed.query).items()
        if k not in TRACKING_PARAMS
    }
    return parsed._replace(query=urlencode(clean_params, doseq=True)).geturl()
```

**적용 소스**: 모든 소스 (Google RSS, Naver, Finnhub 모두 적용)

---

### Step 4. 필터링

#### 4-A. 날짜 필터

수집 시점 기준 **24시간 초과 기사는 분석 대상에서 제외**한다.  
RSS 피드에 오래된 기사가 포함되는 경우를 걸러낸다.

```python
from datetime import datetime, timezone, timedelta

def is_recent(published_at: datetime, threshold_hours: int = 24) -> bool:
    now = datetime.now(timezone.utc)
    return (now - published_at) <= timedelta(hours=threshold_hours)
```

| 수집 시점 | 허용 범위 | 이유 |
|----------|---------|------|
| 09:00 수집 | 전일 15:30 이후 | 장 마감 후 ~ 다음날 장 시작 전 기사 |
| 15:30 수집 | 당일 09:00 이후 | 장 중 발생한 기사 |

> 단순 24시간 필터로 시작하고, 실제 누락 기사 발생 시 시점별 임계값으로 세분화한다.

---

#### 4-B. snippet 최소 길이 필터

snippet이 없거나 너무 짧으면 LLM 분석에 투입해도 의미 없다.

```
탈락 케이스:
  None        → snippet 미제공
  ""          → 빈 문자열
  "삼성전자..."  → 10자 미만 truncation
```

```python
def has_valid_snippet(snippet: str | None, min_length: int = 20) -> bool:
    if not snippet:
        return False
    return len(snippet.strip()) >= min_length
```

| 임계값 | 이유 |
|--------|------|
| 20자 | "삼성전자 3분기 실적 발표" 수준의 최소 맥락 전달 가능 길이 |

---

### Step 5. 중복 제거

**세 단계**로 중복을 제거한다. 각 단계는 서로 다른 레이어에서 작동한다.

#### 5-A. DB 레벨 — URL unique 제약 (수집 단계에서 처리)

`news` 테이블의 `url` 컬럼에 `UniqueConstraint`가 있어 동일 URL은 수집 시점에 이미 차단된다. Step 3에서 URL을 정규화한 뒤 URL이 변경되면 DB에 업데이트한다.

```python
# URL 정규화 후 기존 레코드와 충돌 가능 — 처리 방안
stmt = (
    update(News)
    .where(News.id == news_id)
    .values(url=resolved_url)
)
# ON CONFLICT: 동일 URL이 이미 존재하면 현재 레코드 삭제
```

---

#### 5-B. 제목 텍스트 유사도 — 배치 내 처리 (신규)

URL은 다르지만 **제목이 거의 동일한 기사**를 제거한다.  
연합뉴스·AP 등 통신사 기사는 Google RSS, Naver, 각 언론사 RSS에서 동시에 수집된다.  
URL이 모두 다르므로 5-A를 통과하지만 임베딩 전에 제거할 수 있다.

**방식**: 제목의 2-gram(bigram) Jaccard 유사도. 임베딩 없이 텍스트만으로 계산 가능하다.

```python
import re

def title_bigrams(title: str) -> set[tuple]:
    tokens = re.sub(r'[^\w\s]', '', title).split()
    return set(zip(tokens, tokens[1:])) if len(tokens) > 1 else {(t,) for t in tokens}

def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def deduplicate_by_title(
    news_list: list[dict],
    threshold: float = 0.8,
) -> list[dict]:
    # 최신 기사 우선 보존
    sorted_items = sorted(news_list, key=lambda x: x["published_at"], reverse=True)
    kept: list[tuple[set, dict]] = []
    for item in sorted_items:
        bigrams = title_bigrams(item["title"])
        is_dup = any(jaccard(bigrams, seen_bg) >= threshold for seen_bg, _ in kept)
        if not is_dup:
            kept.append((bigrams, item))
    return [item for _, item in kept]
```

| 파라미터 | 기본값 | 근거 |
|---------|--------|------|
| `threshold` | 0.8 | 제목 단어의 80% 이상 겹치면 동일 기사로 판정. 동일 이슈지만 다른 앵글의 기사는 통과 |

**예상 효과**: 통신사 기사 중복 제거 기준 20~30% 추가 감소. 임베딩 API 호출 비용에 직접 영향.

---

#### 5-C. 벡터 유사도 — 임베딩 후 처리 (EmbeddingClusteringAgent 담당)

같은 이슈를 다룬 다른 언론사 기사는 제목이 달라도 내용이 유사하다.  
이 중복은 임베딩 생성 후 cosine similarity로 제거한다. → **EmbeddingClusteringAgent** 담당이므로 이 단계에서는 처리하지 않는다.

---

### Step 5 → DB 업데이트

필터를 통과한 레코드는 정제된 값으로 업데이트하고 `preprocessed_at`을 기록한다.  
날짜·snippet 필터 탈락 레코드는 삭제하지 않고 `preprocessed_at`만 기록해  
"처리는 됐으나 분석 제외"임을 표시한다.

```python
from datetime import datetime, timezone

async def save_preprocessed(db: AsyncSession, records: list[dict]) -> None:
    now = datetime.now(timezone.utc)
    for record in records:
        await db.execute(
            update(News)
            .where(News.id == record["id"])
            .values(
                snippet=record["snippet"],
                url=record["url"],
                original_url=record.get("original_url"),
                published_at=record["published_at"],
                preprocessed_at=now,
                # 필터 탈락 시 분석 파이프라인 스킵
                is_analyzed=record.get("skip_analysis", False),
            )
        )
    await db.commit()
```

---

## 4. 전처리 모듈 설계

전처리는 `CollectionAgent` 내부에서 `save_tool`을 호출하기 전에 인라인으로 실행된다.  
별도 에이전트가 아닌 `services/preprocessor/` 모듈로 구현한다.

### 4.1 모듈 구성

```python
# CollectionAgent의 save_tool 호출 직전
from services.preprocessor.normalizer import Normalizer
from services.preprocessor.filter import Filter
from services.preprocessor.deduplicator import UrlDeduplicator

async def run(self) -> PreprocessingAgentState:
    """preprocessed_at IS NULL 레코드를 배치로 처리"""
    while True:
        batch = await fetch_unprocessed(limit=BATCH_SIZE)  # preprocessed_at IS NULL
        if not batch:
            break
        cleaned   = await Normalizer.run_all(batch)       # HTML, 타임존, URL (3-A,3-B)
        filtered  = Filter.run(cleaned)                  # 날짜, snippet 길이
        url_dedup = UrlDeduplicator.deduplicate(filtered) # URL unique (5-A)
        deduped   = TitleDeduplicator.deduplicate(url_dedup)  # 제목 유사도 (5-B)
        await save_preprocessed(deduped)                 # preprocessed_at = now()
```

### 4.2 URL 정규화 병렬 처리

Google RSS URL 정규화는 HTTP 요청이 필요하므로 배치 내에서 병렬 처리한다.

```python
# 배치 내 병렬 — 최대 50건 동시
google_items = [item for item in items if "news.google.com" in item["url"]]
semaphore = asyncio.Semaphore(50)
resolved = await asyncio.gather(
    *[resolve_google_rss_url(item["url"], semaphore) for item in google_items],
    return_exceptions=True,
)
```

---

## 5. 소스별 전처리 적용 매트릭스

| 단계 | Google RSS (ko) | Google RSS (en) | Naver API | Finnhub |
|------|:--------------:|:---------------:|:---------:|:-------:|
| 1. HTML 정제 | — | — | ✅ | — |
| 2. 타임존 정규화 | ✅ KST→UTC | ✅ KST→UTC | ✅ KST→UTC | ✅ Unix→UTC |
| 3-A. URL 리다이렉트 해소 | ✅ | ✅ | — | — |
| 3-B. 트래킹 파라미터 제거 | ✅ | ✅ | ✅ | ✅ |
| 4-A. 날짜 필터 | ✅ | ✅ | ✅ | ✅ |
| 4-B. snippet 길이 필터 | ✅ | ✅ | ✅ | ✅ |
| 5-A. URL 중복 제거 | ✅ | ✅ | ✅ | ✅ |
| 5-B. 제목 유사도 중복 제거 | ✅ | ✅ | ✅ | ✅ |

---

## 6. 에러 처리

| 시나리오 | 처리 방식 |
|---------|---------|
| HTML 정제 실패 | 원본 snippet 유지, 계속 진행 |
| 타임존 파싱 실패 | `created_at` (수집 시각)으로 대체, WARNING 로그 |
| URL 리다이렉트 해소 실패 (timeout) | 원본 Google URL 유지, 계속 진행 |
| 트래킹 파라미터 제거 실패 | 원본 URL 유지, 계속 진행 |
| URL 충돌 (정규화 후 중복) | 현재 레코드 제외, 기존 레코드 유지 |
| snippet 길이 부족 | 해당 레코드 저장하지 않음 (탈락) |
| DB 저장 실패 | 배치 롤백, 다음 실행 시 재처리 |

---

## 7. DB 변경 사항

### `news` 테이블 추가 컬럼

URL 변경 이력 추적을 위한 컬럼을 추가한다.

```python
original_url = Column(String(500), nullable=True)  # 정규화 전 원본 URL (Google RSS)
```

URL 정규화 후 `url`을 실제 URL로 업데이트하고 `original_url`에 Google 리다이렉트 URL을 보관한다.

---

## 8. 구현 로드맵

| 단계 | 내용 | 산출물 | 선행 조건 |
|------|------|--------|---------|
| 1 | `normalizer.py` 구현 (HTML 정제 + 타임존) | `services/preprocessor/normalizer.py` | — |
| 2 | `filter.py` 구현 (날짜 필터) | `services/preprocessor/filter.py` | — |
| 3 | `deduplicator.py` 구현 (URL + 제목 유사도) | `services/preprocessor/deduplicator.py` | — |
| 4 | `PreprocessingAgent` 노드 조립 | `services/agents/preprocessing_agent.py` | 1~3 완료 |
| 5 | `news` 테이블 `original_url` 컬럼 추가 | Alembic 마이그레이션 | Alembic 설정 |
| 6 | 통합 테스트 (소스별 샘플 100건) | — | 수집 에이전트 완료 |

---

## 참고 자료

- [`01-agent-orchestration-design.md`](./01-agent-orchestration-design.md) — PreprocessingAgent 상태·에러 처리 전략
- [`02-news-collection-design.md`](./02-news-collection-design.md) — 소스별 수집 형식 상세
