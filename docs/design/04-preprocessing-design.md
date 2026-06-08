# 전처리 기획서

> **작성자** Kim minkyoung · **작성일** 2026-05-28
>
> **범위** 수집 완료 → 전처리 → 임베딩 파이프라인 인계
>
> **관련 문서**
>
> - [파이프라인 오케스트레이션](./01-pipeline-orchestration-design.md)
> - [뉴스 데이터 수집 기획서](./02-news-collection-design.md)
> - [기업 데이터 수집 기획서](./03-company-data-collection-design.md)

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
| HTML 태그 포함 | 일부 RSS `title`의 태그·엔티티 | 임베딩 품질 저하, LLM 혼란 |
| 타임존 불일치 | 소스별 UTC/KST 혼용 | 날짜 필터·정렬 오류 |
| 트래킹 파라미터 | utm_source, fbclid 등 | URL unique 제약 오작동 |
| 중복 기사 | 동일 이슈를 여러 소스가 동시 보도 | 임베딩 비용 낭비, 클러스터 왜곡 |
| 오래된 기사 | RSS 피드에 과거 기사 포함 | 분석 파이프라인에 stale 데이터 투입 |

### 1.2 전처리의 위치 — 수집·전처리·저장을 한 흐름으로

전처리는 **수집 결과를 인메모리로 정제한 뒤 한 번에 저장**한다. 원시 데이터를 먼저 저장하고 나중에 UPDATE하는 DB 핸드오프 방식을 쓰지 않는다.

```
[수집] → 수집 결과 리스트 (인메모리, 미저장)
                    ↓
         [전처리] HTML 정제 → URL 정규화 → 날짜 필터 → 제목 중복 제거
                    ↓
         DB 저장 1회 (정제본, ON CONFLICT(url) DO NOTHING, 탈락분 is_filtered=True)
                    ↓
         [임베딩·클러스터링] ← is_filtered = FALSE AND embedding IS NULL
                    ↓
              [분석 파이프라인]
```

**왜 인메모리인가.** 타임존·URL 정규화를 수집 시점/저장 직전에 끝내고 나면, 전처리에 남는 일(HTML 정제·날짜 필터·제목 중복)은 **외부 호출 없는 순수 CPU 연산**이다. 중간에 실패해 재시도·재개할 외부 의존성이 없으므로, 원시 저장 후 UPDATE하는 DB 핸드오프(더블 라이트 + `preprocessed_at` 상태 컬럼)는 이득 없이 복잡도만 늘린다. 따라서 수집→전처리→저장을 **한 Airflow Task**로 묶고, DB 핸드오프는 외부 API에 의존해 독립 실패·재시도가 필요한 **임베딩 이후 단계에만** 남긴다.

**임베딩 단계로의 인계.** 저장된 시점에 이미 전처리 완료이므로 별도 `preprocessed_at` 상태 컬럼이 필요 없다. 임베딩 단계(EmbeddingClusterer)는 `is_filtered = FALSE AND embedding IS NULL` 조건으로 조회해 전처리를 통과한(필터 탈락 제외) 레코드만 임베딩한다.

> **정규화 시점.** 타임존(KST)은 피드 파싱 시점에 결정되므로 **수집 단계**(`rss_collector`)가 처리한다. HTML 정제·URL 트래킹 파라미터 제거·필터·중복 제거는 저장 직전 **인메모리 전처리**가 한 번에 처리한다. 저장 전에 끝나므로 URL은 항상 정규화된 상태로 `ON CONFLICT(url)`에 걸려, 비정규화 URL이 별도 행으로 새는 문제가 없다.

### 1.3 처리 대상

- **뉴스** (`news` 테이블): 소스별로 HTML·타임존·URL 정규화 필요
- **공시** (`disclosures` 테이블): DART 공공 데이터, HTML·타임존 이슈 없음 → 전처리 불필요

---

## 2. 전처리 파이프라인

총 4단계. 타임존은 수집 시점에 KST로 정규화되므로(§1.2), 전처리는 수집 결과 리스트를 받아 인메모리로 처리한다. 순서가 중요하다 — 정규화(HTML·URL) → 필터링 → 중복 제거 순서로 진행한다.

```
[수집 결과 리스트] (인메모리, 미저장)
    │
    ▼
Step 1. HTML 정제
    │    title HTML 태그·HTML 엔티티 제거
    ▼
Step 2. URL 정규화
    │    utm_source, fbclid 등 트래킹 파라미터 제거
    ▼
Step 3. 날짜 필터
    │    24시간 초과 제외 (published_at 없으면 수집 시각으로 폴백)
    ▼
Step 4. 중복 제거
    │    4-A. 제목 텍스트 유사도 중복 제거 (실행 내 처리)
    │    4-B. URL unique 제약 (저장 시 ON CONFLICT(url) DO NOTHING)
    │    4-C. 벡터 유사도 중복 제거 (EmbeddingClusterer 담당)
    │
    ▼
DB 저장 1회 (정제본 + 탈락분 is_filtered=True, ON CONFLICT(url) DO NOTHING)
```

> **타임존(전처리 범위 밖):** 발행 시각의 KST 정규화는 수집 단계(`rss_collector`)가 처리한다. 상세·근거는 §3.0.

---

## 3. 단계별 상세

### 3.0 타임존 — 수집 시점 KST 정규화 (전처리 범위 밖)

발행 시각의 KST 정규화는 전처리가 아니라 **수집 시점**에 처리한다(§1.2). 경계를 명확히 하기 위해 기록만 남긴다. 소스마다 시간 형식이 다르다.

| 소스 | 형식 | 예시 |
|------|------|------|
| 국내 증권 RSS | RFC 2822 (KST) | `"Thu, 28 May 2026 09:00:00 +0900"` |
| investing.com RSS | RFC 2822 (UTC) | `"Thu, 28 May 2026 00:00:00 +0000"` |

수집 단계에서 feedparser가 파싱한 시각을 **KST naive datetime**으로 정규화해 저장한다. DB 전 테이블이 KST naive 기준(`DateTime(timezone=False)`)으로 통일돼 있다.

- **비용**: 타임존 변환은 행 단위 연산이라 배치로 묶어도 줄지 않는다. feedparser가 수집 중 이미 `published_parsed`(struct_time)를 파싱하므로, 그 자리에서 변환하는 것이 가장 싸다.
- **일관성**: 정규화된 값이 들어가야 날짜 필터·정렬·디버깅 쿼리가 소스에 무관하게 같은 기준을 본다.

```python
# 구현: services/collector/rss_collector.py:_parse_published() + utils/dates.to_naive_kst()
# struct_time(UTC) 우선, 없으면 원본 문자열 파싱.
# 오프셋 없는 시각은 UTC로 가정해 경로별 9시간 어긋남을 방지한다.
```

> 이하 Step 1~4는 수집 결과 리스트를 받아 **저장 직전에 인메모리로** 실행한다(`services/preprocessor/news_preprocessor.py`).

---

### Step 1. HTML 정제

**문제**: 일부 RSS 피드의 `title`에 HTML 태그·엔티티(`&amp;`, `&lt;` 등)가 포함될 수 있다. (본문·snippet은 저장하지 않으므로 정제 대상은 `title`뿐이다.)

```
입력:  "<b>삼성전자</b> 3분기 영업이익 &amp;전년 대비..."
출력:  "삼성전자 3분기 영업이익 &전년 대비..."
```

```python
import html
import re

_TAG_PATTERN = re.compile(r"<[^>]+>")

def clean_title(title: str) -> str:
    if not title:
        return ""
    text = html.unescape(title)        # &amp; → &
    text = _TAG_PATTERN.sub("", text)  # <b> 등 태그 제거
    return text.strip()
```

모든 소스에 일괄 적용한다. 이미 plain text인 경우 변환 비용이 낮아 무해하다. (외부 의존성 없이 stdlib만 사용 — title은 짧아 정규식으로 충분하다.)

---

### Step 2. URL 정규화 (트래킹 파라미터 제거)

**문제**: 동일 기사 URL에 추적 파라미터가 붙어 다른 URL로 인식된다.

```
같은 기사:
  https://hankyung.com/article/123?utm_source=naver&utm_medium=news
  https://hankyung.com/article/123?fbclid=abc123
  https://hankyung.com/article/123
```

저장 직전에 트래킹 파라미터를 제거하므로, 저장 시 `ON CONFLICT(url) DO NOTHING`이 정규화된 URL로 같은 기사를 차단한다. **저장 전 단계**라 비정규화 URL이 먼저 새어 별도 행으로 저장되는 일이 없다(B 방식의 사후 충돌 삭제 불필요).

```python
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term",
    "fbclid", "gclid", "ref", "source",
})

def remove_tracking_params(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    kept = [
        (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k not in TRACKING_PARAMS
    ]
    return urlunparse(parsed._replace(query=urlencode(kept)))  # 쿼리 순서 보존
```

**적용 소스**: 모든 RSS 피드. 파싱 실패 시 원본 URL 유지(§6).

---

### Step 3. 날짜 필터

수집 시점 기준 **24시간 초과 기사는 분석 대상에서 제외**한다.  
RSS 피드에 오래된 기사가 포함되는 경우를 걸러낸다.

```python
from datetime import datetime, timedelta

def is_recent(
    published_at: datetime | None,
    now: datetime,
    threshold_hours: int = 24,
    *,
    fallback: datetime | None = None,
) -> bool:
    # published_at이 None이면 fallback(수집 시각)으로 대체. 미래 시각도 통과.
    reference = published_at or fallback
    if reference is None:
        return False
    return reference >= now - timedelta(hours=threshold_hours)
```

> **published_at = None 처리**: 일부 RSS는 발행일을 주지 않거나 파싱에 실패해 `published_at`이 `None`이다(§6). 인메모리 처리 시점에는 아직 `created_at`이 없으므로 **수집 시각(`now`)을 폴백**으로 쓴다 — 방금 수집된 기사이므로 항상 통과한다.

| 수집 시점 | 허용 범위 | 이유 |
|----------|---------|------|
| 09:00 수집 | 전일 15:30 이후 | 장 마감 후 ~ 다음날 장 시작 전 기사 |
| 15:30 수집 | 당일 09:00 이후 | 장 중 발생한 기사 |

> 단순 24시간 필터로 시작하고, 실제 누락 기사 발생 시 시점별 임계값으로 세분화한다.

---

### Step 4. 중복 제거

**세 레이어**로 중복을 제거한다. 각 레이어는 서로 다른 단계에서 작동한다.

#### 4-A. 제목 텍스트 유사도 — 실행 내 처리 (전처리)

URL은 다르지만 **제목이 거의 동일한 기사**를 제거한다.  
통신사(연합뉴스·AP 등) 기사는 여러 언론사 RSS에서 동시에 수집된다.  
URL이 모두 다르므로 4-B(url unique)를 통과하지만 임베딩 전에 제거할 수 있다.

**방식**: 제목의 2-gram(bigram) Jaccard 유사도. 임베딩 없이 텍스트만으로 계산 가능하다.

```python
import re

_PUNCT_PATTERN = re.compile(r"[^\w\s]")

def title_bigrams(title: str) -> set[tuple]:
    tokens = _PUNCT_PATTERN.sub("", title).split()
    return set(zip(tokens, tokens[1:])) if len(tokens) > 1 else {(t,) for t in tokens}

def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

def deduplicate_by_title(
    items: list[dict],
    threshold: float = 0.8,
) -> tuple[list[dict], list[dict]]:
    # 최신 기사 우선 보존. (보존, 중복) 두 리스트 반환.
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
```

| 파라미터 | 기본값 | 근거 |
|---------|--------|------|
| `threshold` | 0.8 | 제목 단어의 80% 이상 겹치면 동일 기사로 판정. 동일 이슈지만 다른 앵글의 기사는 통과 |

**예상 효과**: 통신사 기사 중복 제거 기준 20~30% 추가 감소. 임베딩 API 호출 비용에 직접 영향.

> **경계 — 실행 내 한정**: 같은 전처리 실행(= 한 수집 런) 안에서만 비교한다. 09:00·15:30 두 런에 걸친 중복은 잡지 못하지만, 의미 중복은 임베딩 단계 4-C가 잡으므로 값싼 1차 필터로 둔다.

---

#### 4-B. URL unique 제약 — 저장 시 처리

Step 2에서 URL을 정규화했으므로, 저장 시 `upsert_news`의 `ON CONFLICT(url) DO NOTHING`이 동일 URL(이전 런에 이미 저장된 기사 포함)을 차단한다. 전처리가 별도로 처리할 일은 없다.

---

#### 4-C. 벡터 유사도 — 임베딩 후 처리 (EmbeddingClusterer 담당)

같은 이슈를 다룬 다른 언론사 기사는 제목이 달라도 내용이 유사하다.  
이 중복은 임베딩 생성 후 cosine similarity로 제거한다. → **EmbeddingClusterer** 담당이므로 이 단계에서는 처리하지 않는다.

---

### Step 4 → DB 저장

전처리는 정제된 레코드 리스트를 반환하고, 저장은 `save_tool.upsert_news`가 한 번에 수행한다.  
날짜 필터·제목 중복 탈락 레코드는 삭제하지 않고 `is_filtered=True`로 표시해 함께 저장한다 —  
"처리는 됐으나 분석 제외"임을 표시한다(임베딩·분석 스킵). 별도 `preprocessed_at` 기록은 없다(저장 시점 = 전처리 완료).

```python
# 전처리: 수집 리스트 → 정제본(+is_filtered) 반환 (DB 접근 없음)
records, stats = run_preprocessing(collected, now=now_kst())
# 저장: url ON CONFLICT DO NOTHING으로 멱등 저장 (1회)
saved = await upsert_news(db, records)
```

---

## 4. 전처리 모듈 설계

전처리는 수집 결과를 인메모리로 정제하는 **순수 함수** `run_preprocessing`으로 구현한다(`services/preprocessor/news_preprocessor.py`). DB 접근이 없어 단위 테스트가 쉽고, 수집→전처리→저장을 한 Airflow Task가 조립한다(오케스트레이션은 Phase 7).

### 4.1 모듈 구성

```python
# services/preprocessor/news_preprocessor.py — run_preprocessing()
def run_preprocessing(
    records: list[dict],          # CollectedNews.to_record() 형식 (미저장)
    *,
    now: datetime | None = None,
    threshold_hours: int = 24,
    dup_threshold: float = 0.8,
) -> tuple[list[dict], PreprocessStats]:
    now = now or now_kst()
    items = [{**r, **dict(zip(("title", "url"), normalize(r["title"], r["url"]))),
              "is_filtered": False} for r in records]   # Step 1·2 정규화
    for item in items:                                  # Step 3 날짜 필터 (now 폴백)
        if not is_recent(item.get("published_at"), now, threshold_hours, fallback=now):
            item["is_filtered"] = True
    survivors = [it for it in items if not it["is_filtered"]]
    _, dups = deduplicate_by_title(survivors, dup_threshold)  # Step 4-A 제목 중복
    for dup in dups:
        dup["is_filtered"] = True
    return items, stats   # 탈락분도 is_filtered=True로 함께 반환
```

> 수집 노드는 `collected = await rss_collector.collect()` → `records, _ = run_preprocessing([c.to_record() for c in collected])` → `await upsert_news(db, records)` 순으로 조립한다.

---

## 5. 소스별 전처리 적용 매트릭스

| 단계 | 담당 | 국내 증권 RSS (13개) | investing.com RSS (3개) |
|------|------|:-----------------:|:--------------------:|
| 타임존 정규화 (KST) | 수집(§3.0) | ✅ | ✅ |
| Step 1. HTML 정제 | 전처리 | ✅ | ✅ |
| Step 2. URL 트래킹 파라미터 제거 | 전처리 | ✅ | ✅ |
| Step 3. 날짜 필터 | 전처리 | ✅ | ✅ |
| 4-A. 제목 유사도 중복 제거 | 전처리 | ✅ | ✅ |
| 4-B. URL 중복 제거 | 저장 unique 제약 | ✅ | ✅ |

---

## 6. 에러 처리

| 시나리오 | 처리 방식 | 단계 |
|---------|---------|------|
| 발행일 없음·타임존 파싱 실패 | 수집이 `published_at=None`으로 넘김 → 날짜 필터에서 수집 시각(`now`)으로 폴백 | 수집→전처리 |
| HTML 정제 실패 | 원본 title 유지, 계속 진행 | 전처리 |
| 트래킹 파라미터 제거 실패 | 원본 URL 유지, 계속 진행 | 전처리 |
| 날짜 필터·제목 중복 탈락 | 삭제 안 함, `is_filtered=True`로 표시해 저장 (임베딩·분석 스킵) | 전처리 |
| URL 충돌 (정규화 후 중복) | 저장 시 `ON CONFLICT(url) DO NOTHING`으로 차단 | 저장 |
| DB 저장 실패 | 저장 롤백, 다음 수집 런에서 재수집·재처리 | 저장 |

---

## 7. DB 변경 사항

### `news` 테이블 — 저장 시 채우는 컬럼

전처리는 정제된 레코드를 반환하고 `upsert_news`가 한 번에 INSERT한다. 저장 시 채워지는 전처리 관련 컬럼:

| 컬럼 | 내용 |
|------|------|
| `title` · `url` | 정제·정규화된 값 (HTML 제거, 트래킹 파라미터 제거) |
| `is_filtered` | 24시간 초과·제목 중복으로 분석 제외 시 `True` |

> - `published_at`은 **수집 시점에 KST 정규화**된 값이 그대로 저장된다.
> - `is_filtered`(전처리 제외)와 `is_analyzed`(분석 완료)는 의미가 다르므로 분리한다 — 통과율 집계 시 의미 오염 방지. 임베딩 단계는 `is_filtered = FALSE AND embedding IS NULL`로 조회한다(§1.2).

> **`preprocessed_at` 컬럼 — 미사용(제거 보류).** 인메모리 방식에서는 저장 시점 = 전처리 완료이므로 핸드오프 키가 불필요하다. 모델의 `preprocessed_at` 컬럼은 **마이그레이션을 보류**해 당장은 남겨두되 더는 읽거나 쓰지 않는다(항상 `NULL`). 임베딩 단계 구현 시 다른 스키마 변경과 함께 제거한다.

---

## 8. 구현 로드맵

| 단계 | 내용 | 산출물 | 상태 |
|------|------|--------|------|
| 1 | `run_preprocessing` 구현 (HTML·URL·필터·제목중복, 인메모리) | `services/preprocessor/news_preprocessor.py` | ✅ 구현됨 |
| 2 | 단위 테스트 (순수 함수 + 파이프라인 조립) | `tests/test_news_preprocessor.py` | ✅ 구현됨 |
| 3 | 수집 노드 조립 (`collect → run_preprocessing → upsert_news`) | `services/pipeline/news_collector.py` | Phase 7 |
| 4 | `preprocessed_at` 컬럼 제거 마이그레이션 | Alembic | 임베딩 단계와 함께 |

> 단계 1·2는 완료됐다. 단계 3(오케스트레이션)과 단계 4(컬럼 제거 마이그레이션)는 후속이다 — 타임존 정규화는 이미 [`rss_collector.py`](../../services/collector/rss_collector.py)에 구현돼 있다.

---

## 참고 자료

- [`01-pipeline-orchestration-design.md`](./01-pipeline-orchestration-design.md) — Preprocessor 상태·에러 처리 전략
- [`02-news-collection-design.md`](./02-news-collection-design.md) — 소스별 수집 형식 상세
