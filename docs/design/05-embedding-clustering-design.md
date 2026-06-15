# 임베딩·클러스터링 기획서

> **작성자** Kim minkyoung · **작성일** 2026-05-28 (2026-06-12 핵심 압축 개정)
>
> **범위** 전처리 완료 → 임베딩 생성 → 클러스터링 → 분석 파이프라인 인계
>
> **핵심 결정**: 모델 `gemini-embedding-001`(768, 3축 평가 전 축 1위) · 입력 title 단독(실험2로 재확인) · 중복 cosine≥0.95 soft-flag · HDBSCAN(mcs=2, ms=1) + 싱글톤 보존 · 복합 중요도 → top 10 → `news_cluster` UPSERT. **코어 파이프라인 구현·실완주 검증 완료(2026-06-11).**
>
> **관련 문서**: [01 오케스트레이션](./01-pipeline-orchestration-design.md) · [04 전처리](./04-preprocessing-design.md) · [임베딩 모델 평가 보고서](../evaluation/00-embedding-model-evaluation.md)

---

## 목차

- [1. 목적](#1-목적)
- [2. 임베딩 전략](#2-임베딩-전략)
- [3. pgvector 인덱스 설정](#3-pgvector-인덱스-설정)
- [4. 유사도 기반 중복 제거](#4-유사도-기반-중복-제거)
- [5. 클러스터링 알고리즘 비교 및 선택](#5-클러스터링-알고리즘-비교-및-선택)
- [6. 주요 이슈 선정 — 복합 중요도 스코어](#6-주요-이슈-선정--복합-중요도-스코어)
- [7. RAG 소스 준비 — ReportChunk 임베딩](#7-rag-소스-준비--reportchunk-임베딩)
- [8. EmbeddingClusterer 설계](#8-embeddingclusterer-설계)
- [9. 임베딩 텍스트 정책 — 테이블별](#9-임베딩-텍스트-정책--테이블별)
- [10. 구현 로드맵](#10-구현-로드맵)
- [11. 미결 사항](#11-미결-사항)

---

## 1. 목적

```
전처리 완료 (embedding=NULL) → 임베딩 생성 → 근접 중복 표시(is_duplicate, soft)
  → 클러스터링(같은 이슈 묶기) → 복합 중요도로 오늘의 주요 이슈 선정(news_cluster 적재)
  → 분석 파이프라인 인계
```

임베딩 용도: ① 유사 중복 제거(대표 1건만 분석) ② 클러스터링(Issue Docent 기반) ③ RAG 검색(기업 컨텍스트).

**처리 대상**: `news`(`is_filtered=FALSE AND embedding IS NULL`) · `report_chunks`(`embedding IS NULL`, 전처리 불필요).

---

## 2. 임베딩 전략

### 2.1 임베딩 모델 비교

**확정: `gemini-embedding-001`(768 절단, MRL) — 2026-06-09.** 후보 최대 12종을 실데이터 3축(비지도·라벨 클러스터링·RAG)으로 평가, 전체 기록은 [평가 보고서](../evaluation/00-embedding-model-evaluation.md)가 단일 출처.

| 모델 | ari | silhouette | RAG recall@5 | 판정 |
|------|-----|-----------|--------------|------|
| **gemini-embedding-001 (✅ 채택)** | **0.307** | **0.443** | **0.931** | 세 축 모두 1위 |
| KURE-v1 (1024) | 0.227 | 0.364 | 0.862 | 근소 열위 + 1024 마이그레이션 비용 |
| ko-sroberta (baseline) | 0.213 | 0.337 | 0.690 | 2021 모델, 기준선 |

채택 근거: ① 파이프라인 직결 지표(ari·recall) 단독 1위 ② MRL 768 절단으로 **현 `Vector(768)` 스키마 유지** ③ Vertex로 LLM 분석과 인프라 통일. 금융특화(nmixx·kf-deberta)·후속 v2도 교체 실익 없음. 모델 변경 = 임베딩 전체 재계산이므로 첫 배포 전에 확정했다. 평가 교훈: **모델별 호출 규약(task_type/instruction) 검증 필수.**

환경 변수: `EMBED_MODEL=gemini-embedding-001` · `EMBED_DIM=768` (1024 모델 전환 시 전 테이블 동시 마이그레이션).

### 2.2 임베딩 텍스트 구성

**채택: title 단독** (`build_embed_text`). 주식 뉴스 제목은 키워드 밀도가 높아 동일 이슈를 묶기에 충분하고, 본문을 쓰려면 클러스터링이 대표 선정 *이전* 단계라 **당일 전체 기사 fetch(~31배 비용)**가 필요하다.

> ✅ **실험2로 재확인(2026-06-11)**: title vs title+body 비교(185건) — 본문 추가 시 silhouette 0.495→0.443으로 오히려 하락, 군집 ARI 0.407. 본문은 클러스터링을 개선하지 않는다. feed summary 결합(중간안)도 불채택.

저작권 제약 재확인(→ [02 §3](./02-news-collection-design.md#3-저작권-및-법적-검토)): 본문·snippet은 DB 저장 금지 — 어떤 방식이든 메모리 임베딩 후 폐기만 가능.

### 2.3 배치 처리

Vertex AI 한도에 맞춰 `EMBED_BATCH_SIZE=50`씩 분할 호출. 일별 추정 ~38~60회(200~500종목 기준). 구현: [`embedding_client.py`](../../services/embedder/embedding_client.py) — 모델명 기반 백엔드 분기(Vertex/genai/HF), task_type 반영, lazy 생성.

---

## 3. pgvector 인덱스 설정

HNSW(`m=16, ef_construction=64`, cosine)를 `news`·`report_chunks`에 — ANN으로 O(log n) 유사도 검색. **벡터가 쌓이기 전 생성**한다(누적 후 빌드는 오래 걸림). 적용 완료(마이그레이션 52b04bf7383d).

---

## 4. 유사도 기반 중복 제거

### 4.1 두 가지 임계값

| 목적 | 임계값 | 의미 |
|------|--------|------|
| 중복 제거 | cosine ≥ 0.95 | 거의 동일한 기사 (받아쓰기) |
| 이슈 클러스터링 | (HDBSCAN 밀도 기반) | 같은 이슈를 다룬 다른 기사 |

### 4.2 중복 제거 (cosine ≥ 0.95) — 하드 삭제가 아니라 soft flag

중복 판정 기사는 **삭제하지 않고 `is_duplicate=TRUE`로 표시**한다. 같은 쌍 중 **발행 시각(없으면 수집 시각)이 늦은 쪽**을 표시하고 이른 쪽을 대표로 남긴다 — RSS는 발행순 전달이 보장되지 않아 id 순서를 쓰지 않고, `COALESCE(published_at, created_at)` + id 타이브레이크로 전순서를 보장한다. 클러스터링·분석은 `is_duplicate=FALSE`만 읽는다.

**왜 삭제하지 않나**: 하드 DELETE는 ① `news_cluster` FK 정합성 위협 ② URL 유니크 행 제거로 재수집→재임베딩 비용 재발 ③ "무엇이 중복으로 빠졌는지" 추적 차단. soft flag는 셋을 모두 피하고 상태 컬럼 기반 핸드오프와 일관되며, 재실행 멱등하다.

**대상 창**: 당일 수집분 — `settings.pipeline_window_hours`(24h, KST) 기준 cutoff를 **파이썬에서 계산해 전달**한다(`created_at`이 KST naive라 SQL `NOW()`(UTC)와 직접 비교하면 9시간 어긋남). 구현: [`deduplicator.py`](../../services/preprocessor/deduplicator.py).

---

## 5. 클러스터링 알고리즘 비교 및 선택

### 5.1~5.2 채택: HDBSCAN

| 알고리즘 | 탈락 사유 |
|---------|----------|
| K-Means | 클러스터 수 사전 지정 필요 — 오늘 이슈가 몇 개인지 모름 |
| 임계값 그룹핑 | 전이적 연결 문제(A≈B, B≈C → A,C 묶임) |
| Agglomerative | O(n² log n) 속도 |
| **HDBSCAN (✅)** | 수 지정 불필요 · noise 자동 분리 · 파라미터 1개 · varying density(금리 50건 vs 단독 2건) 동시 처리 |

구현: [`cluster.py`](../../services/embedder/cluster.py) — precomputed cosine distance, `eom`, 거리 음수 클리핑.

### 5.3 임계값 도출 방법론

**현재 수치(0.95, mcs=2, ms=1)는 초기 추정값** — 실데이터 교정 절차: ① 같은/다른 이슈 쌍 50쌍씩 수동 라벨 ② cosine 분포 시각화 → valley = 클러스터링 임계값, positive 90th pct = 중복 임계값 (분리 안 되면 P-R 곡선 F1 최대점) ③ 사람이 좋다고 평가한 결과의 silhouette을 합격 기준으로 역산(금융 뉴스는 0.2~0.35도 현실적) ④ 환경 변수 반영. 상류 FilterChain `confidence`의 의미 검증(구간별 사람 평가)도 별도 가치.

### 5.4 Singleton 처리 — 기본 보존

HDBSCAN의 noise(-1)는 "주제 무관"이 아니라 **"오늘 한 곳만 보도한 단독 기사"**다 — 코퍼스가 이미 2중 정제(증권 RSS + 전처리)됐기 때문. 단독 보도는 오히려 잠재 고가치이므로 버리지 않고 **size-1 클러스터로 승격**(`promote_singletons`)해 동일 기준으로 importance를 경쟁시킨다. 우선순위는 `TOP_ISSUE_COUNT` 컷오프가 결정 — 임의 임계값 없이 스코어가 정렬한다.

### 5.5 클러스터링 품질 검증

자동 지표 `evaluate_clustering`: silhouette(noise 제외, cosine)·davies_bouldin·n_clusters·noise_ratio. 정성 체크: 같은 이슈가 같은 클러스터인가 / 다른 이슈가 분리되는가 / singleton이 합리적인가 / 20건 초과 클러스터 재검토 / noise 50%↑면 mcs 축소.

### 5.6 min_cluster_size · min_samples 선정

**초기값 `mcs=2, ms=1`** — 2개 이상 언론사 보도 시 클러스터 형성, noise 최소(싱글톤 보존 §5.4와 정합). 두 파라미터는 상호작용하므로 2D 그리드 스윕으로 교정한다: noise>60% → 둘 다↓ / 거대 클러스터 쏠림 → ms↑ / 과분할 → mcs↑.

### 5.7 차원 축소 — 불필요

768차원은 HNSW로 충분(일별 ~수백 건, 거리행렬 ~14MB). 1024 모델 전환 + 성능 문제 시에만 PCA 먼저, 부족하면 UMAP.

### 5.8 대표 기사 선정 — 1건 + 중심 근접순 후보

대표는 **1건**(`representative_news_id` = member[0])이되, `member_news_ids`를 **클러스터 중심 근접순으로 정렬 저장**(`order_by_centrality`) — 스키마 변경 없이 ① 대표 1건 ② fetch 실패 시 다음 후보 fallback ③ 다관점 후보를 모두 커버. 대표 3건 분석은 토큰·fetch 3배 + 중복 서술 위험이라 기각.

환경 변수: `CLUSTER_MIN_CLUSTER_SIZE=2` · `CLUSTER_MIN_SAMPLES=1` · `DEDUP_SIMILARITY_THRESHOLD=0.95` · `PIPELINE_WINDOW_HOURS=24`.

---

## 6. 주요 이슈 선정 — 복합 중요도 스코어

클러스터 단위 평가라 임베딩·클러스터링 후에만 가능 — 본 절이 신호·가중치·구현의 단일 출처.

### 6.0 선정 방법론 — 벤치마크와 중요도 신호

벤치마크: **카카오 RUBICS**(Volume — 클러스터 크기 상위 = 주요 이슈), **Bloomberg**(Velocity — 기사 급증 시 상단). 신호 5종 중 Volume·Velocity·Sentiment·Entity는 MVP, Social(구글 트렌드)은 확장.

> **가중치 W는 학술 단일 출처 없는 휴리스틱 초기값** — 실데이터 교정 전까지 확정값이 아니다(→ §11).

### 6.1 스코어 계산

각 신호를 [0,1] 정규화 후 가중합 — `W = {volume: 0.4, velocity: 0.3, sentiment: 0.15, entity: 0.15}`.

- `volume_n` = 크기 / 당일 최대 크기
- `velocity_n` = 이전 대비 증가율 [0,1] 클리핑. **prev=0(이전 관측 없음)이면 0** — 원안의 `(size-prev)/(prev+1)`은 prev=0에서 전부 1이 되는 결함이 있어 교정(2026-06-11).
- sentiment·entity는 상류(NER·감성) 연결 전까지 0 (MVP, → §11) — 현재는 볼륨 지배 정렬(RUBICS와 정합).

구현: [`score.py`](../../services/embedder/score.py).

### 6.2 상위 이슈 선정·영속화

`persist_clusters`: 클러스터당 1행을 `news_cluster`에 **(run_date, representative_news_id) 기준 UPSERT** — 재실행은 멱등하고, 오후(15:30) 런에서 같은 클러스터가 새 기사로 크면 소속·크기·중요도를 **갱신**한다(DO UPDATE). importance 내림차순 상위 `TOP_ISSUE_COUNT=10` 대표 id를 반환해 분석에 인계.

---

## 7. RAG 소스 준비 — ReportChunk 임베딩

`report_chunks`의 `embedding IS NULL` 청크를 같은 단계에서 임베딩(`ReportEmbedder`, task_type=RETRIEVAL_DOCUMENT) — 분석 단계 ImpactAnalysisChain의 기업 컨텍스트 소스.

### 7.2 기업 컨텍스트 검색

`app/llm/rag.py`의 `get_company_context(db, company, k=3)` — 쿼리를 RETRIEVAL_QUERY로 임베딩해 pgvector `<=>`(cosine)로 상위 k 청크 검색(비대칭 임베딩). langchain PGVector 의존성 없이 raw pgvector + ORM으로 구현(중복 제거와 방식 일관). 매칭 없으면 빈 문자열 → 호출부가 "확실치 않음" 처리(RAG 엣지케이스 → 06).

---

## 8. EmbeddingClusterer 설계

### 8.1~8.3 구성과 실행

```
[embed_news ∥ embed_chunks (asyncio.gather, 독립 세션)]
  → deduplicate (cosine ≥ 0.95 soft flag)
  → cluster (HDBSCAN, is_duplicate=FALSE·당일 창)
  → score_and_select (복합 중요도 → news_cluster UPSERT → top 10)
```

- State(XCom 보고): `news_embedded`/`chunks_embedded`/`duplicates_removed`/`clusters_formed`/`top_issues`/`errors`.
- **당일 창은 run()에서 1회 계산**해 dedup·클러스터링에 같은 값 전달(창 불일치 방지).
- 임베딩 한쪽 실패는 errors에 담고 나머지 단계 진행(부분 실패 격리). AsyncSession은 동시 사용 불가라 병렬 임베딩은 각자 독립 세션.
- 클라이언트 lazy 생성 — 작업 0건 런은 백엔드 구축 비용 0.

구현: [`embedding_clusterer.py`](../../services/pipeline/embedding_clusterer.py). 실완주 검증(2026-06-11): 임베딩 778+91 → 중복 92 → 클러스터 190 → top 10, errors 0. 멱등성 2회 연속 실행 PASS(2회차 신규 적재 0).

> 남은 상태 머신 조각: `is_analyzed=TRUE` 마감은 **분석 단계(06)**가 담당 — 06 연결 전까지 게이트는 열려 있고, 당일 창이 재클러스터링 범위를 한정한다.

---

## 9. 임베딩 텍스트 정책 — 테이블별

| 테이블 | 임베딩 텍스트 | task_type | 이유 |
|--------|------------|------|------|
| `news` | `title` | CLUSTERING | 제목만 저장, 키워드 밀도 충분(§2.2) |
| `report_chunks` | `content` 전체 | RETRIEVAL_DOCUMENT | RAG 검색 정확도 우선 |
| `disclosures` | `f"{title}. {content[:500]}"` | (분석 단계 구현 시) | 공시 제목 + 본문 앞부분 |

---

## 10. 구현 로드맵

| 단계 | 내용 | 상태 |
|:---:|------|:---:|
| 1~2 | pgvector 활성화 + HNSW 인덱스 | ✅ |
| 3 | `news_embedder.py` (배치 임베딩) | ✅ |
| 4 | `deduplicator.py` (유사도 soft flag) | ✅ |
| 5 | `cluster.py` (HDBSCAN + 싱글톤 보존 + 중심 정렬) | ✅ |
| 6 | `report_embedder.py` (RAG 청크) | ✅ |
| 7 | `app/llm/rag.py` (기업 컨텍스트 검색) | ✅ |
| 8 | `EmbeddingClusterer` 조립 | ✅ (2026-06-11, 실완주·멱등 검증) |
| 9 | 통합 테스트 (분석 연결 후 재검증) | 1차 ✅ |

---

## 11. 미결 사항

| 항목 | 내용 | 상태 |
|------|------|------|
| 임베딩 모델 | `gemini-embedding-001`(768) | ✅ 확정 (2026-06-09) |
| 임베딩 텍스트 | title 단독 — 실험2로 재확인 | ✅ 확정 (2026-06-11) |
| 가중치 W 교정 | 0.4/0.3/0.15/0.15 휴리스틱 → 실데이터 튜닝 | ⬜ 데이터 누적 후 |
| Sentiment·Entity·Social 신호 | LLM/FinBERT 감성, NER 연동(06), 구글 트렌드 | ⬜ 06 구현 시·MVP 이후 |
| `prev_cluster_size` 추적 | velocity 계산용 이전 크기 저장 방법 | ⬜ 신호 통합 시 |
| 클러스터링 임계값 교정 | (mcs, ms) 2D 스윕 + cosine valley (§5.3·§5.6) | ⬜ 데이터 누적 후 |
| TOP_ISSUE_COUNT | 상위 10개 적정성 | ⬜ 서비스 기획 조율 |
| 임베딩 도구 수준 retry | 현재 Airflow retries가 1차 방어 — with_retry 보강 | ⬜ 06 구현 시 |
