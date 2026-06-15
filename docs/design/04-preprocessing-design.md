# 전처리 기획서

> **작성자** Kim minkyoung · **작성일** 2026-05-28 (2026-06-12 핵심 압축 개정)
>
> **범위** 수집 완료 → 전처리 → 임베딩 파이프라인 인계
>
> **핵심 결정**: 수집 결과를 **인메모리 순수 함수**로 정제 후 1회 저장 (원시 저장 후 UPDATE하는 DB 핸드오프 안 씀). 순서: HTML → URL → 날짜 → 제목 중복. 탈락분은 삭제 대신 `is_filtered=True`. 구현: [`services/preprocessor/news_preprocessor.py`](../../services/preprocessor/news_preprocessor.py)

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

---

## 1. 목적

### 1.1 전처리가 필요한 이유

소스마다 형식·품질이 불균일하다 — HTML 태그(임베딩 품질 저하), 타임존 혼용(필터·정렬 오류), 트래킹 파라미터(URL unique 오작동), 중복 기사(임베딩 비용·클러스터 왜곡), 오래된 기사(stale 투입).

### 1.2 전처리의 위치 — 수집·전처리·저장을 한 흐름으로

```
[수집] → 인메모리 정제 (HTML → URL → 날짜 → 제목 중복) → DB 저장 1회
       → [임베딩·클러스터링] ← is_filtered=FALSE AND embedding IS NULL
```

**왜 인메모리인가.** 타임존·URL 정규화를 수집/저장 직전에 끝내면 전처리에 남는 일은 **외부 호출 없는 순수 CPU 연산**이다. 재시도할 외부 의존성이 없으므로 원시 저장 후 UPDATE(더블 라이트 + 상태 컬럼)는 이득 없이 복잡도만 늘린다 → 수집→전처리→저장을 **한 Airflow Task**로 묶고, DB 핸드오프는 외부 API 의존 단계(임베딩 이후)에만 남긴다.

**임베딩 인계.** 저장 시점 = 전처리 완료이므로 별도 상태 컬럼(`preprocessed_at`) 불필요 — EmbeddingClusterer가 `is_filtered=FALSE AND embedding IS NULL`로 이어받는다.

**정규화 시점.** 타임존(KST)은 피드 파싱 시점이 가장 싸므로 **수집 단계**가, 나머지는 저장 직전 인메모리 전처리가 처리한다. URL이 저장 전에 정규화되므로 `ON CONFLICT(url)`이 정확히 동작한다(비정규화 URL 누출 없음).

### 1.3 처리 대상

뉴스(`news`)만. 공시(`disclosures`)는 DART 공공 데이터라 HTML·타임존 이슈가 없어 전처리 불필요.

---

## 2. 전처리 파이프라인

총 4단계, **정규화 → 필터 → 중복 제거 순서**가 중요하다.

```
Step 1. HTML 정제 (title 태그·엔티티)
Step 2. URL 정규화 (트래킹 파라미터 제거)
Step 3. 날짜 필터 (24h 초과 제외, published_at 없으면 수집 시각 폴백)
Step 4. 중복 제거 — 4-A 제목 유사도(실행 내) · 4-B URL unique(저장 시) · 4-C 벡터 유사도(05 담당)
→ DB 저장 1회 (탈락분 is_filtered=True 포함)
```

---

## 3. 단계별 상세

### 3.0 타임존 — 수집 시점 KST 정규화 (전처리 범위 밖)

국내 RSS는 KST(+0900), investing.com은 UTC(+0000) — 수집 단계가 **KST naive datetime**으로 정규화한다(DB 전 테이블 KST naive 통일). 오프셋 없는 시각은 UTC로 가정해 9시간 어긋남을 방지. 구현: `rss_collector._parse_published()` + `utils/dates.to_naive_kst()`.

### Step 1. HTML 정제 (`clean_title`)

`html.unescape` + 태그 제거 정규식, stdlib만 사용. 정제 대상은 `title`뿐(본문 미저장). 예: `"<b>삼성전자</b> &amp;..."` → `"삼성전자 &..."`.

### Step 2. URL 정규화 (`remove_tracking_params`)

`utm_*`·`fbclid`·`gclid`·`ref`·`source` 제거 — 같은 기사가 트래킹 파라미터 차이로 다른 행이 되는 것을 차단. 저장 **전** 정규화라 사후 충돌 정리가 필요 없다.

### Step 3. 날짜 필터 (`is_recent`)

수집 시점 기준 **24시간 초과 제외**. `published_at=None`이면 수집 시각(`now`) 폴백 — 방금 수집분은 항상 통과. (09:00 런 = 전일 장 마감 후 기사, 15:30 런 = 당일 장중 기사를 커버.)

### Step 4. 중복 제거 — 세 레이어

| 레이어 | 방식 | 작동 시점 |
|------|------|------|
| **4-A 제목 유사도** | 제목 bigram **Jaccard ≥ 0.8** — 통신사 받아쓰기(URL 다름) 제거. 같은 실행 내 한정(런 간은 4-C가 처리). 효과 ~20-30% 감소 | 전처리 |
| **4-B URL unique** | `ON CONFLICT(url) DO NOTHING` — 이전 런 포함 동일 URL 차단 | 저장 |
| **4-C 벡터 유사도** | cosine ≥ 0.95 soft flag — **EmbeddingClusterer 담당** (→ [05 §4.2](./05-embedding-clustering-design.md#42-중복-제거-cosine--095--하드-삭제가-아니라-soft-flag)) | 임베딩 후 |

**저장**: 탈락분(날짜·제목 중복)은 삭제하지 않고 `is_filtered=True`로 함께 저장 — "처리됐으나 분석 제외" 표시, 통과율 집계 가능.

---

## 4. 전처리 모듈 설계

`run_preprocessing(records, *, now, threshold_hours=24, dup_threshold=0.8)` — DB 접근 없는 **순수 함수**라 단위 테스트가 쉽다. 수집 노드가 `collect → run_preprocessing → upsert_news`로 조립(→ [02 §7](./02-news-collection-design.md#7-뉴스-수집-단계)). 구현·시그니처 정본: [`news_preprocessor.py`](../../services/preprocessor/news_preprocessor.py).

---

## 5. 소스별 전처리 적용 매트릭스

타임존(수집)·Step 1~4-B 전부 국내 13피드·investing.com 3피드에 **동일 적용** — 소스별 분기 없음.

---

## 6. 에러 처리

| 시나리오 | 처리 |
|---------|------|
| 발행일 없음·파싱 실패 | `published_at=None` → 날짜 필터에서 수집 시각 폴백 |
| HTML 정제·URL 정규화 실패 | 원본 유지, 계속 진행 |
| 필터·중복 탈락 | 삭제 안 함, `is_filtered=True`로 저장 |
| URL 충돌 | `ON CONFLICT(url) DO NOTHING` |
| DB 저장 실패 | 롤백 → 다음 수집 런에서 재수집·재처리 |

---

## 7. DB 변경 사항

저장 시 채워지는 전처리 관련 컬럼: `title`·`url`(정제·정규화된 값), `is_filtered`(탈락 표시).

- `is_filtered`(전처리 제외)와 `is_analyzed`(분석 완료)는 의미가 달라 분리 — 통과율 집계 시 의미 오염 방지.
- **`preprocessed_at` 컬럼은 제거 완료**(2026-06-11 마이그레이션 c6fd3e4b6185) — 인메모리 전환으로 항상 NULL인 죽은 컬럼이었다.

---

## 8. 구현 로드맵

| 단계 | 내용 | 상태 |
|------|------|:---:|
| 1 | `run_preprocessing` (인메모리 4단계) | ✅ |
| 2 | 단위 테스트 (`tests/test_news_preprocessor.py`) | ✅ |
| 3 | 수집 노드 조립 (`news_collector.py`) | ✅ |
| 4 | `preprocessed_at` 제거 마이그레이션 | ✅ (2026-06-11) |
