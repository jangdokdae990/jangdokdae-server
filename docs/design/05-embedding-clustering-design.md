# 임베딩·클러스터링 기획서

> **작성자** Kim minkyoung · **작성일** 2026-05-28
>
> **범위** 전처리 완료 → 임베딩 생성 → 클러스터링 → 분석 파이프라인 인계
>
> **관련 문서**
>
> - [파이프라인 오케스트레이션](./01-pipeline-orchestration-design.md)
> - [전처리 기획서](./04-preprocessing-design.md)
> - [기업 데이터 수집 기획서](./03-company-data-collection-design.md)
> - [임베딩 모델 비교 결과 (1차)](../evaluation/00-embedding-model-comparison-result.md) — §11 모델 확정용 비교

---

## 목차

- [1. 목적](#1-목적)
- [2. 임베딩 전략](#2-임베딩-전략)
- [3. pgvector 인덱스 설정](#3-pgvector-인덱스-설정)
- [4. 유사도 기반 중복 제거](#4-유사도-기반-중복-제거)
- [5. 클러스터링 알고리즘 비교 및 선택](#5-클러스터링-알고리즘-비교-및-선택)
- [6. 주요 이슈 선정 — 복합 중요도 스코어](#6-주요-이슈-선정--복합-중요도-스코어)
- [7. RAG 소스 준비 — ReportChunk 임베딩](#7-rag-소스-준비-—-reportchunk-임베딩)
- [8. EmbeddingClusterer 설계](#8-embeddingclusterer-설계)
- [9. 임베딩 텍스트 정책 — 테이블별](#9-임베딩-텍스트-정책-—-테이블별)
- [10. 구현 로드맵](#10-구현-로드맵)
- [11. 미결 사항](#11-미결-사항)
- [참고 자료](#참고-자료)

---

## 1. 목적

### 1.1 임베딩·클러스터링이 하는 일

```
전처리 완료 데이터 (embedding=NULL)
    │
    ▼
임베딩 생성 (텍스트 → 벡터)
    │
    ▼
유사도 기반 중복 제거 (거의 동일한 기사 제거)
    │
    ▼
클러스터링 (같은 이슈 묶기)
    │
    ▼
오늘의 주요 이슈 선정 (복합 중요도 스코어 → news_cluster 적재)
    │
    ▼
분석 파이프라인 인계 (is_analyzed=False 레코드)
```

### 1.2 임베딩이 필요한 이유

| 용도 | 설명 |
|------|------|
| **유사도 기반 중복 제거** | 같은 이슈를 다룬 다른 언론사 기사를 벡터 유사도로 묶어 대표 1건만 분석 |
| **클러스터링** | 오늘 수집된 기사를 주제별로 그룹화해 Issue Docent 생성 기반 마련 |
| **RAG 검색** | 분석 파이프라인에서 기업 컨텍스트 검색 (ImpactAnalysisChain의 related_companies) |

### 1.3 처리 대상

| 테이블 | 트리거 | 용도 |
|--------|--------|------|
| `news` | `is_filtered = FALSE AND embedding IS NULL` | 전처리 통과분 임베딩 (탈락분 `is_filtered=TRUE` 제외) |
| `report_chunks` | `embedding IS NULL` | 사업보고서 RAG 소스 준비 (전처리 불필요) |

---

## 2. 임베딩 전략

### 2.1 임베딩 모델 비교

장독대는 한국어 금융 뉴스를 주로 다루므로 모델 선택이 클러스터링·RAG 품질에 직접적인 영향을 미친다.  
**실제 데이터로 비교 테스트 후 최종 확정한다.** (→ 섹션 11 미결 사항 참조)

---

#### 후보 모델 전체 비교

모델 선택은 두 축으로 본다 — **관리형(Vertex AI, 인프라 통일)** vs **오픈소스(한국어 특화 가능)**.

| 모델 | 차원 | 운영 방식 | 한국어 | 금융 도메인 | 벤치마크 | 비고 |
|------|------|---------|--------|-----------|---------|------|
| `gemini-embedding-001` | 3072→768 (MRL) | Vertex AI (관리형) | ✅✅ | △ | **MTEB Multilingual 1위** | 관리형 유력 후보 |
| `nlpai-lab/KURE-v1` | 1024 | 로컬 / HuggingFace | ✅✅ | △ | **MTEB-ko-retrieval 1위** | 오픈소스 유력 후보 |
| `BAAI/bge-m3` | 1024 | 로컬 / HuggingFace | ✅✅ | △ | 최상위권 | KURE의 base |
| `jhgan/ko-sroberta-multitask` | 768 | 로컬 | ✅✅ | △ | 중상위 | 현재 코드 기본값·baseline |
| `text-multilingual-embedding-002` | 768 | Vertex AI (관리형) | ✅ | △ | 미공개 | **레거시** (gemini로 대체) |
| `FinKRX` | — | 미공개 | ✅✅ | ✅✅ | — | 임베딩 버전 미공개 (LLM) |

> **차원 주의**: `gemini-embedding-001`은 기본 3072이나 **Matryoshka(MRL)로 768·1536 무손실 절단** 가능 → 768로 잘라 쓰면 현재 `Vector(768)` 스키마 유지. 반면 `KURE-v1`·`bge-m3`는 **1024차원**이라 전환 시 `Vector(1024)` 스키마 변경 + 임베딩 전체 재계산이 필요하다.

---

#### 모델별 상세

**`gemini-embedding-001`** (Google, 2025.07 Vertex AI GA) — 관리형 유력 후보
- `text-multilingual-embedding-002`의 후속. MTEB **Multilingual·English·Code 동시 1위** (Multilingual Task Mean 68.32)
- 100+개 언어, 최대 입력 2048 토큰. **Matryoshka(MRL)** 로 3072→1536→768 무손실 절단
- 768로 절단하면 **현재 `Vector(768)` 스키마 그대로** + Vertex/Gemini 인프라 통일 (별도 서버 불필요)
- API 호출당 과금 (현재 기획서 기준 ~38~60회/일)

**`nlpai-lab/KURE-v1`** (고려대학교 NLP&AI 연구실, 2024.12 공개) — 오픈소스 유력 후보
- BGE-M3 기반으로 **한국어 검색에 특화** fine-tuning. 하드 네거티브 마이닝 적용
- **MTEB-ko-retrieval 1위**, 특히 **장문 검색**에서 강점 → 사업보고서 RAG 청크 검색에 유리
- 1024 차원 → 전환 시 `Vector(1024)` 스키마 변경 필요
- 로컬 GPU 또는 HuggingFace Inference API 사용

**`BAAI/bge-m3`**
- 70개 언어 지원 다국어 모델. KURE-v1의 base 모델
- 단일 모델로 dense·sparse·multi-vector 세 가지 검색 방식 지원, 1024 차원
- 한국어 단독 성능은 KURE-v1이 상회 → KURE-v1을 오픈소스 대표 후보로 둠

**`jhgan/ko-sroberta-multitask`** (baseline)
- **현재 코드 기본값** ([.env.example](../../.env.example): `EMBED_MODEL=jhgan/ko-sroberta-multitask`)
- KorNLI + KorSTS로 학습, 한국어 STS에서 안정적. 768 차원
- 2021년 모델로 최신 모델 대비 성능 낮음 → **비교 baseline으로만 사용**

**`text-multilingual-embedding-002`** (Vertex AI) — 레거시
- `gemini-embedding-001` 출시로 사실상 대체됨. MTEB-ko 공개 벤치마크 없어 품질 불확실
- 신규 채택하지 않음 (gemini로 시작)

**`FinKRX`** (원라인AI + 한국거래소, ACL 2025 등재)
- 최초 한국 금융 특화 언어모델. 국내 금융 텍스트에 최적화
- **현재 임베딩 모델로 직접 사용 불가** (LLM). 임베딩 파인튜닝 버전 공개 여부 확인 필요
- 향후 공개되면 RAG 소스 임베딩에 특히 유리할 것으로 예상

---

#### 운영 방식 트레이드오프

| 구분 | Vertex AI (관리형) | 로컬 / HuggingFace |
|------|------------------|------------------|
| 인프라 추가 | 없음 | GPU 서버 또는 HuggingFace API |
| 비용 | API 호출당 과금 | 서버 고정비 또는 HF API 비용 |
| 성능 한도 | gemini-embedding-001 = MTEB 다국어 1위 | KURE-v1 = 한국어 검색 특화 |
| 유지보수 | 없음 | 모델 업데이트 관리 필요 |
| 스키마 영향 | 768 절단 시 변경 없음 | 1024차원 → 스키마 변경 |

> **모델은 아직 미확정**이다. 위 비교는 후보 정리이며, 실제 장독대 데이터로 [§11 비교 하니스](#11-미결-사항)를 돌려 확정한다. 유력 후보는 관리형 `gemini-embedding-001`(768 절단 → 스키마 유지·Vertex 통일)과 오픈소스 `KURE-v1`(한국어 검색 1위, 1024). 모델 변경 시 기존 임베딩 **전체 재계산**이 필요하므로 **첫 배포 전 비교 테스트로 결정**한다.

---

#### 후보 비교 축 (결정은 §11 테스트 이후)

```
gemini-embedding-001 (768 절단)  ← Vertex 인프라 통일, 스키마 유지, MTEB 다국어 1위
        ↕  실데이터 비교 테스트(pair_auc·ARI·RAG recall)로 선택
KURE-v1 (1024)                   ← 한국어 검색 1위, 장문 RAG 강점 (스키마 변경 동반)
        +
ko-sroberta-multitask (768)      ← 현재 코드 기본값, baseline
```

환경 변수 (코드의 `EMBED_MODEL` 네이밍, **값은 테스트 후 확정**):
```
EMBED_MODEL=<비교 테스트 후 확정>   # 후보: gemini-embedding-001 / nlpai-lab/KURE-v1
EMBED_DIM=<모델에 따라 768 또는 1024>
```

> **현재 코드 상태**: [.env.example](../../.env.example)는 `EMBED_MODEL=jhgan/ko-sroberta-multitask`(baseline), `EMBED_DIM` 없음, ORM `Vector(768)` 하드코딩. 모델 확정 시 `.env`·설정·스키마를 함께 갱신한다.

---

### 2.2 임베딩 텍스트 구성

뉴스 메타데이터로 **제목만** 저장하므로 임베딩 입력도 title 단독으로 한다.

```python
def build_embed_text(title: str) -> str:
    return title
```

**채택: title 단독.** 주식 뉴스 제목은 핵심 키워드 밀도가 높아 title만으로도 동일 이슈를 묶는 데 실용적으로 충분하다.  
(`"삼성전자 3분기 영업이익 9.2조"`, `"삼성전자 분기 실적 어닝서프라이즈"` → 같은 클러스터로 묶임)

#### 본문을 클러스터링에 쓰지 않는 이유 — 비용 구조

본문이 클러스터링 품질을 올릴 여지는 있으나, **클러스터링은 대표기사 선정 *이전* 단계**라 본문을 쓰려면 **당일 전체 기사**를 fetch해야 한다. 분석 단계(상위 ~10건만 fetch)와 비용 차수가 다르다.

| 방식 | 본문 fetch 위치 | 일별 fetch 수 | 저장 | 리스크 |
|------|--------------|-------------|------|--------|
| **title만 (채택)** | 분석 단계 대표기사만 | **~10회/일** | 없음 | 제목 모호 시 품질 저하 |
| title + feed summary | 없음 (RSS 응답 내 summary 메모리 사용) | 0회 추가 | 없음(메모리 후 폐기) | 피드별 summary 유무·길이 편차 |
| title + 전체 본문 fetch | **클러스터링 단계 전체** | **~310회/일 (31배)** | 없음(메모리) | 페이월·타임아웃이 **임계 경로**에서 발생, 일 처리 지연 |

> **저작권 제약 재확인**(→ [02 §3](./02-news-collection-design.md)): 본문·snippet은 **DB 저장 금지**. 어떤 방식이든 메모리에서 임베딩 후 폐기만 가능하다. feed summary 결합도 벡터만 남기고 원문은 저장하지 않는다.

#### 구현 시 실험 (Phase 2, 클러스터링 구현 시점)

title 단독으로 시작하되, 라벨셋으로 다음을 측정해 품질 부족이 확인되면 **feed summary 결합(중간안)** 으로 전환한다. 전체 본문 fetch는 비용·취약성 때문에 후순위.

```python
# 같은 라벨셋(같은이슈/다른이슈 쌍 50쌍씩)으로 입력 구성만 바꿔 비교
VARIANTS = {
    "title_only":      lambda n: n.title,
    "title_summary":   lambda n: f"{n.title}. {n.feed_summary}",  # 메모리 한정, 미저장
}
# 평가: positive/negative cosine 분리도(AUC) + 사람 라벨 대비 ARI
# → title_only로 valley 분리가 충분하면 그대로 확정, 부족하면 title_summary 채택
```

---

### 2.3 배치 처리

Vertex AI API 요청 제한을 고려해 배치 단위로 처리한다.

```python
from vertexai.language_models import TextEmbeddingModel

EMBED_BATCH_SIZE = 50  # Vertex AI 최대 허용 배치 크기

async def embed_batch(texts: list[str]) -> list[list[float]]:
    model = TextEmbeddingModel.from_pretrained(settings.EMBED_MODEL)
    # 50건씩 나눠서 호출
    results = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        embeddings = model.get_embeddings(batch)
        results.extend([e.values for e in embeddings])
    return results
```

**일별 임베딩 API 호출 추정:**

| 수집량 | 배치 크기 | API 호출 수 |
|--------|---------|------------|
| 200종목 기준 ~1,900건/일 | 50 | ~38회/일 |
| 500종목 기준 ~3,000건/일 | 50 | ~60회/일 |

---

## 3. pgvector 인덱스 설정

### 3.1 HNSW 인덱스

인덱스 없이 클러스터링하면 전체 테이블 스캔(O(n))이 발생한다. HNSW는 근사 최근접 이웃(ANN) 검색으로 O(log n) 수준의 빠른 유사도 검색을 제공한다.

```sql
-- 뉴스 임베딩 인덱스 (pgvector 활성화 직후 생성)
CREATE INDEX idx_news_embedding
    ON news USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 사업보고서 청크 인덱스
CREATE INDEX idx_report_chunks_embedding
    ON report_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);
```

**HNSW 파라미터:**

| 파라미터 | 값 | 의미 |
|---------|-----|------|
| `m` | 16 | 그래프 연결 수. 높을수록 정확하지만 메모리 증가 |
| `ef_construction` | 64 | 인덱스 빌드 품질. 높을수록 정확하지만 빌드 느림 |

> 벡터가 많이 쌓인 뒤 인덱스를 추가하면 빌드 시간이 길어진다. **pgvector 활성화 직후, 첫 데이터 저장 전에 생성**한다.

---

## 4. 유사도 기반 중복 제거

### 4.1 두 가지 임계값

중복 제거와 클러스터링은 목적이 다르므로 임계값을 분리한다.

| 목적 | 임계값 | 의미 |
|------|--------|------|
| **중복 제거** | cosine ≥ 0.95 | 거의 동일한 기사 (받아쓰기 기사) |
| **이슈 클러스터링** | cosine ≥ 0.80 | 같은 이슈를 다룬 다른 기사 |

### 4.2 중복 제거 (cosine ≥ 0.95)

```python
async def deduplicate_by_similarity(
    db: AsyncSession,
    threshold: float = 0.95,
) -> int:
    """임베딩 유사도 기반 중복 제거 — 당일 수집분 대상"""
    # pgvector로 유사도 0.95 이상인 쌍 찾기
    # 같은 쌍 중 published_at이 늦은 것(나중에 수집된 것)을 제거
    query = """
        DELETE FROM news
        WHERE id IN (
            SELECT n2.id
            FROM news n1
            JOIN news n2 ON n1.id < n2.id
            WHERE 1 - (n1.embedding <=> n2.embedding) >= :threshold
              AND n1.published_at <= n2.published_at
              AND n1.created_at >= NOW() - INTERVAL '1 day'
        )
    """
    result = await db.execute(query, {"threshold": threshold})
    return result.rowcount
```

---

## 5. 클러스터링 알고리즘 비교 및 선택

### 5.1 알고리즘 비교

| 알고리즘 | 클러스터 수 사전 지정 | 노이즈 처리 | 파라미터 수 | 장독대 적합성 |
|---------|------------------|-----------|-----------|------------|
| **K-Means** | 필요 (k) | ❌ 모든 점 할당 | 1개 | ❌ — 뉴스 클러스터 수 예측 불가 |
| **임계값 그룹핑** | 불필요 | △ singleton 발생 | 1개 (threshold) | △ — 단순하지만 전이적 연결 문제 |
| **DBSCAN** | 불필요 | ✅ noise 자동 분리 | 2개 (ε, min_samples) | ✅ — 노이즈·밀도 모두 처리 |
| **HDBSCAN** | 불필요 | ✅✅ | 1개 (min_cluster_size) | ✅✅ — DBSCAN 개선, 밀도 변화 대응 |
| **Agglomerative** | threshold 지정 | △ | 2개 | △ — O(n² log n), 속도 문제 |

---

### 5.2 채택: HDBSCAN

**이유:**

1. **클러스터 수 사전 지정 불필요**: 오늘 주요 이슈가 3개인지 20개인지 알 수 없음
2. **노이즈 자동 분리**: DBSCAN과 달리 ε 파라미터 없이 밀도 기반으로 noise 자동 분류
3. **파라미터 1개** (`min_cluster_size`): 최소 기사 수만 지정하면 나머지는 데이터가 결정
4. **varying density 처리**: 대형 이슈(금리 결정 50건)와 소형 이슈(단독 보도 2건) 동시 처리
5. **임계값 기반보다 품질 우수**: 임계값 기반의 전이적 연결 문제(A≈B, B≈C → A,C 같은 클러스터)를 피함

```python
import hdbscan
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

def cluster_news(
    embeddings: np.ndarray,
    min_cluster_size: int = 2,   # 클러스터 최소 기사 수
    min_samples: int = 1,        # 노이즈 민감도 조절
) -> np.ndarray:
    """
    HDBSCAN 뉴스 클러스터링
    반환: 각 기사의 클러스터 레이블 (-1 = noise/singleton)
    """
    # cosine distance matrix (1 - cosine_similarity)
    distance_matrix = 1 - cosine_similarity(embeddings)

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="precomputed",
        cluster_selection_method="eom",  # excess of mass — 자연스러운 클러스터 선택
    )
    labels = clusterer.fit_predict(distance_matrix)
    return labels  # array([ 0,  0,  1, -1,  1,  2, -1, ...])
                   # -1 = noise (singleton 포함)
```

---

### 5.3 임계값 도출 방법론

> **현재 기획서의 모든 수치(0.95, 0.80, 0.7, 0.3)는 초기 추정값이다.**  
> 실제 장독대 뉴스 데이터로 아래 실험을 수행해 도출해야 한다.  
> 환경 변수로 관리하므로 코드 수정 없이 업데이트 가능하다.

---

#### 임계값별 도출 실험

**① cosine similarity 임계값 (중복 제거: 0.95 / 클러스터링: 0.80)**

같은 이슈 기사 쌍(positive)과 다른 이슈 기사 쌍(negative)의 유사도 분포를 시각화한다.  
두 분포가 분리되는 지점(valley)이 자연스러운 임계값이다.

```python
import matplotlib.pyplot as plt

# 실험용 레이블 샘플 준비 (100쌍 수동 레이블링)
# positive: 같은 날 같은 이슈를 다룬 기사 쌍
# negative: 같은 날 다른 이슈를 다룬 기사 쌍
positive_sims = [cosine_sim(a, b) for a, b in positive_pairs]
negative_sims = [cosine_sim(a, b) for a, b in negative_pairs]

plt.hist(positive_sims, bins=20, alpha=0.6, label="같은 이슈 쌍")
plt.hist(negative_sims, bins=20, alpha=0.6, label="다른 이슈 쌍")
plt.xlabel("Cosine Similarity")
plt.legend()
# → 두 분포가 분리되는 valley 지점 = 클러스터링 임계값
# → positive 중 90th percentile 이상 = 중복 제거 임계값
```

**기대 분포 형태:**
```
중복 제거 임계값 (0.95 추정):  positive 상위 5~10% — 거의 같은 기사
클러스터링 임계값 (0.80 추정): 두 분포가 갈라지는 valley 지점
```

실제 분포가 명확히 분리되지 않는다면 **Precision-Recall 곡선**으로 최적 임계값 선택.

```python
from sklearn.metrics import precision_recall_curve

labels = [1]*len(positive_sims) + [0]*len(negative_sims)
scores = positive_sims + negative_sims

precision, recall, thresholds = precision_recall_curve(labels, scores)
# F1 최대 지점 = 최적 임계값
f1_scores = 2 * (precision * recall) / (precision + recall + 1e-8)
best_threshold = thresholds[f1_scores.argmax()]
```

---

**② filter_confidence 의미 검증 (상류 FilterChain 품질)**

> singleton은 기본 보존(§5.4)하므로 confidence는 더 이상 singleton 판별 게이트가 아니다. 다만 상류 FilterChain(`is_filtered`)의 신뢰도가 실제 중요도와 일치하는지는 별도로 검증할 가치가 있다.

FilterChain이 반환하는 `confidence` 값의 실제 의미를 검증한다.

```python
# 실험: confidence 구간별 기사 품질 사람이 직접 평가
bins = [(0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.0)]

for low, high in bins:
    sample = [n for n in news_list if low <= n.filter_confidence < high][:10]
    # 각 구간 10건씩 직접 읽고 "주식 투자자에게 중요한가?" 판단
    # → 중요도 비율이 급격히 높아지는 구간 하한 = 임계값
```

**핵심 질문**: "이 기사가 주린이에게 중요한가?"를 사람이 평가했을 때 confidence가 높은 기사일수록 더 많이 동의하는가? 그렇지 않다면 FilterChain 프롬프트 자체를 재검토해야 한다.

---

**③ Silhouette Score 기준 (품질 판단: 0.3)**

금융 뉴스는 유사한 기사가 많아 일반 텍스트보다 낮은 실루엣이 나올 수 있다.  
"사람이 좋다고 느끼는 클러스터링 결과"의 실루엣 점수를 먼저 측정해 기준을 설정한다.

```python
# Step 1: 사람이 평가한 "좋은 클러스터링" 결과로 실루엣 계산
# Step 2: 해당 점수를 합격 기준으로 설정
# 금융 뉴스 특성상 0.2~0.35가 현실적일 수 있음 (일반 텍스트의 0.5 기준보다 낮음)
```

---

**④ 요약 — 전체 임계값 도출 실험 순서**

```
1. 뉴스 수집 후 100~200건 샘플 확보
2. 같은 이슈/다른 이슈 쌍 수동 레이블링 (50쌍씩)
3. cosine similarity 분포 시각화 → 클러스터링·중복 제거 임계값 도출
4. FilterChain 실행 → confidence 구간별 품질 평가 → 상류 필터 신뢰도 검증
5. HDBSCAN 실행 → 사람이 결과 평가 → Silhouette 기준 역산
6. 도출된 값을 환경 변수에 반영
```

**현재 기획서 수치는 이 실험 전 시작점으로만 사용한다.**

---

### 5.4 Singleton 처리 — 기본 보존 (단독 이슈는 고가치)

HDBSCAN이 `-1` (noise)로 분류한 기사는 "한 이슈를 한 곳만 보도한 단독(singleton)"이다. **장독대는 이를 노이즈가 아니라 잠재적 고가치 이슈로 보고 기본 보존한다.**

**근거:**

1. **코퍼스가 이미 2중 정제됨** — 모든 기사가 ① 증권·경제 RSS 도메인, ② FilterChain 통과(`is_filtered=False`)를 거쳤다. 즉 noise(-1)는 "주제 무관 기사"가 아니라 "오늘 같은 이슈를 다른 곳이 안 쓴 기사"다 → 실제 이슈일 기저율이 높다.
2. **단독 보도(exclusive)는 오히려 고가치** — 아직 시장에 퍼지지 않은 정보일 수 있어, 묻어버리면 안 된다.
3. **노이즈 컷은 이미 상류에서 수행됨** — FilterChain(`is_filtered`)이 저품질·무관 기사를 거른다. 클러스터링 단계가 이를 또 거르는 건 과잉이며, 하드코딩 소스 리스트(매직값)도 불필요하다.

**처리 방침 — size-1 클러스터로 편입:**

singleton을 버리거나 별도 분기로 특별 취급하지 않는다. **크기 1의 클러스터로 그대로 importance 스코어링(§6)에 편입**하고, 우선순위는 `TOP_ISSUE_COUNT` 컷오프가 결정하게 한다.

```python
# noise(-1)도 각각 size-1 클러스터로 승격해 스코어링 대상에 포함
def promote_singletons(labels: np.ndarray) -> np.ndarray:
    next_id = labels.max() + 1
    out = labels.copy()
    for i in np.where(labels == -1)[0]:
        out[i] = next_id
        next_id += 1
    return out  # 모든 기사가 클러스터에 소속 → 동일 기준으로 importance 경쟁
```

| 케이스 | 처리 |
|--------|------|
| singleton (FilterChain 통과) | **size-1 클러스터로 보존** → importance 스코어링 → 상위면 분석 인계 |
| 저품질·주제 무관 | 클러스터링 단계가 아니라 **상류 FilterChain(`is_filtered=True`)이 이미 제외** |

> **우선순위 부상 메커니즘**: singleton은 volume_n이 낮으므로(size 1), entity prominence(코스피200·시총)와 sentiment 강도로 부상한다(§6.1). "대형 종목의 단독 호재"는 entity·sentiment로 상위 진입하고, "소형주 잡음성 단독"은 자연히 컷오프 아래로 가라앉는다 — 임의 임계값 없이 스코어가 정렬한다.

---

### 5.5 클러스터링 품질 검증

**자동 지표:**

```python
from sklearn.metrics import silhouette_score, davies_bouldin_score

def evaluate_clustering(
    embeddings: np.ndarray,
    labels: np.ndarray,
) -> dict:
    # noise 제외 (label != -1)
    mask = labels != -1
    if mask.sum() < 2:
        return {"silhouette": None, "davies_bouldin": None}

    return {
        # Silhouette: -1~1, 높을수록 좋음 (0.3 이상이면 양호)
        "silhouette": silhouette_score(
            embeddings[mask], labels[mask], metric="cosine"
        ),
        # Davies-Bouldin: 낮을수록 좋음
        "davies_bouldin": davies_bouldin_score(embeddings[mask], labels[mask]),
        "n_clusters": len(set(labels)) - (1 if -1 in labels else 0),
        "noise_ratio": (labels == -1).sum() / len(labels),
    }
```

**정성 평가 체크리스트 (실제 뉴스 100건 샘플):**

```
✅ 같은 날 "삼성전자 실적 발표"를 다룬 기사들이 같은 클러스터에 있는가?
✅ "코스피 상승"과 "나스닥 하락" 기사가 다른 클러스터인가?
✅ 단독 보도 기사가 합리적인 이유로 singleton이 되었는가?
✅ 클러스터가 너무 크지 않은가? (20건 초과 클러스터는 재검토)
✅ noise 비율이 50% 이상이면 min_cluster_size를 줄여야 함
```

---

### 5.6 min_cluster_size · min_samples 선정

HDBSCAN의 결과는 **두 파라미터의 상호작용**으로 결정된다. 한쪽만 스윕하면 안 된다.

| 파라미터 | 역할 | 올리면 |
|---------|------|--------|
| `min_cluster_size` | 클러스터로 인정할 최소 기사 수 | 클러스터 수↓, 큰 이슈만 남음 |
| `min_samples` | 밀도 보수성(코어 포인트 기준). 클수록 경계 기사를 noise로 봄 | **noise↑**, 클러스터 더 조밀·보수적 |

> `min_samples`를 명시하지 않으면 HDBSCAN은 `min_cluster_size`와 같은 값을 쓴다. 본 설계의 초기값 `min_samples=1`은 **가장 공격적(noise 최소)** 설정으로, singleton 기본 보존(§5.4)과도 잘 맞는다 — 일단 다 클러스터에 넣고 importance가 거르게 한다.

**선정 방법 — 2D 그리드 스윕:**

```python
import numpy as np

mcs_grid  = [2, 3, 4, 5]
ms_grid   = [1, 2, 3, None]   # None = min_cluster_size와 동일(HDBSCAN 기본)

print(f"{'mcs':>4} {'ms':>5} {'n_clusters':>11} {'silhouette':>11} {'noise':>7}")
for mcs in mcs_grid:
    for ms in ms_grid:
        labels  = cluster_news(embeddings, min_cluster_size=mcs, min_samples=ms)
        m       = evaluate_clustering(embeddings, labels)
        sil     = f"{m['silhouette']:.3f}" if m['silhouette'] is not None else "  n/a"
        print(f"{mcs:>4} {str(ms):>5} {m['n_clusters']:>11} {sil:>11} {m['noise_ratio']:>6.1%}")
```

**해석 가이드 (결과표 읽는 법):**

| 관찰 | 의미 | 조치 |
|------|------|------|
| noise_ratio > 60% | 너무 보수적 | `min_samples`↓ 또는 `min_cluster_size`↓ |
| 거대 클러스터 1~2개에 쏠림 | 과합침(over-merge) | `min_samples`↑ |
| n_clusters가 기사 수에 육박 | 과분할 | `min_cluster_size`↑ |
| Silhouette < (§5.3에서 역산한 기준) | 경계 모호 | 두 값 조합 재탐색 |

**초기값: `min_cluster_size=2`, `min_samples=1`** — 같은 이슈를 2개 이상 언론사가 보도하면 클러스터 형성, noise 최소화. 단독 기사는 §5.4에 따라 size-1 클러스터로 보존되므로 noise를 공격적으로 줄여도 정보 손실이 없다.

---

### 5.7 차원 축소 — 필요 여부 판단

**현재 상황:**
- `gemini-embedding-001`(768 절단): **768차원**
- `KURE-v1` / `BGE-M3`: **1024차원**
- HNSW 인덱스: 고차원에서도 효율적 (O(log n))
- 일별 처리 대상: ~1,900건 → 거리 행렬 1,900×1,900 = ~14MB

**결론: 768차원은 차원 축소 불필요.** HNSW가 충분히 처리한다.

**1024차원(KURE-v1·BGE-M3) 사용 시 성능 문제 발생하면:**

```python
from sklearn.decomposition import PCA

def reduce_dimensions(
    embeddings: np.ndarray,
    target_dim: int = 256,
) -> np.ndarray:
    pca = PCA(n_components=target_dim, random_state=42)
    return pca.fit_transform(embeddings)

# 차원 축소 전후 Silhouette Score 비교 — 품질 저하 < 5%이면 축소 채택
```

**PCA vs UMAP:**

| 방법 | 속도 | 클러스터 구조 보존 | 재현성 |
|------|------|----------------|--------|
| PCA | 빠름 | △ (선형만) | ✅ |
| UMAP | 느림 | ✅✅ (비선형) | △ (random seed 필요) |

→ 차원 축소가 필요하다면 **PCA 먼저**, 품질이 부족하면 UMAP 검토.

**하이퍼파라미터 튜닝 (차원 축소 + 클러스터링 통합):**

```python
from itertools import product

# 그리드 서치
target_dims   = [256, 512, 768]
min_cluster_sizes = [2, 3, 4]

best_score, best_params = -1, {}
for dim, mcs in product(target_dims, min_cluster_sizes):
    reduced = reduce_dimensions(embeddings, dim) if dim < 768 else embeddings
    labels  = cluster_news(reduced, min_cluster_size=mcs)
    metrics = evaluate_clustering(reduced, labels)
    if metrics["silhouette"] and metrics["silhouette"] > best_score:
        best_score  = metrics["silhouette"]
        best_params = {"dim": dim, "min_cluster_size": mcs}

print(f"최적 파라미터: {best_params}, Silhouette: {best_score:.3f}")
```

---

### 5.8 대표 기사 선정 — 1건 + 중심 근접순 후보

대표기사는 **1건**(`representative_news_id`)이다. 다만 분석 단계(06 §8.4)는 페이월·fetch 실패 시 **대체 기사를 순차 시도**하므로, `member_news_ids`를 **클러스터 중심 근접순으로 정렬 저장**한다. 그러면 스키마 변경 없이 ① 대표 1건, ② 실패 시 다음 후보 fallback, ③ 필요 시 상위 N건 다관점 입력을 모두 커버한다.

```python
def order_by_centrality(cluster_ids: list[int], embeddings: np.ndarray) -> list[int]:
    """클러스터 중심에 가까운 순으로 기사 id 정렬.
    [0]=대표기사, 이후=fetch fallback·다관점 후보 순서."""
    cluster_embeddings = embeddings[cluster_ids]
    centroid = cluster_embeddings.mean(axis=0)
    sims = cosine_similarity([centroid], cluster_embeddings)[0]
    order = np.argsort(sims)[::-1]            # 유사도 내림차순
    return [cluster_ids[i] for i in order]

# representative_news_id = ordered[0]
# member_news_ids        = ordered  (정렬 보존)
```

> **왜 1건인가**: 대표 3건 본문을 분석에 다 넣으면 LLM 토큰·fetch 비용이 3배이고 같은 이슈를 중복 서술할 위험이 크다. "중심 근접순 정렬 후보"가 동일 효용을 더 싸게 제공한다 — 분석은 [0]만 fetch하고, 막히면 [1], [2]로 내려간다.

---

**환경 변수:**
```
CLUSTER_MIN_CLUSTER_SIZE=2        # HDBSCAN min_cluster_size
CLUSTER_MIN_SAMPLES=1             # HDBSCAN min_samples (noise 최소·singleton 보존)
DEDUP_SIMILARITY_THRESHOLD=0.95   # 중복 제거 임계값
```

> singleton은 기본 보존(§5.4)하므로 `SINGLETON_CONFIDENCE_THRESHOLD`·하드코딩 소스 리스트는 두지 않는다.

---

## 6. 주요 이슈 선정 — 복합 중요도 스코어

클러스터링 완료 후 **오늘 분석할 이슈**를 복합 중요도 스코어로 선정한다. 이 선정은 **클러스터(같은 이슈로 묶인 기사 그룹) 단위 평가**이므로 임베딩·클러스터링이 끝난 뒤에야 가능하다 — 따라서 수집 단계(02)가 아니라 본 단계가 담당한다. 본 절이 신호 정의·가중치·구현의 **단일 출처**다.

### 6.0 선정 방법론 — 벤치마크와 중요도 신호

#### 타 서비스 벤치마크

| 서비스 | 핵심 신호 | 로직 |
|--------|----------|------|
| **카카오 RUBICS** (2015~) | **Volume** | "1시간 동안 같은 이슈로 묶인 기사 수가 많을수록 주요 이슈". 클러스터 크기 상위 = 오늘의 주요 이슈. 실시간 클릭·체류로 순위 보정, 어뷰징(반복 송고) 필터링 |
| **Bloomberg Terminal** | **Velocity** | 같은 종목에 기사가 갑자기 쏟아지면(속도 급증) 상단 노출. Top News(편집자)·감성 점수·AI 3줄 요약 병행 |

#### 중요도 신호 5가지 (금융 뉴스 중요도 연구 공통)

| 신호 | 정의 | 측정 방법 | 도입 |
|------|------|----------|------|
| **Volume** | 같은 이슈 기사 수 | 클러스터 내 기사 수 | MVP |
| **Velocity** | 기사 발행 속도 | 단위 시간(1h)당 급증률 | MVP |
| **Sentiment** | 긍정/부정 강도 | LLM / FinBERT 감성 점수 | MVP |
| **Entity Prominence** | 언급 기업 중요도 | 코스피200 여부·시총 (→ [03](./03-company-data-collection-design.md)) | MVP |
| **Social Signals** | SNS·검색 반응 | 구글 트렌드, 멘션 수 (pytrends 등 외부 API) | 확장 |

장독대는 검증된 **Volume + Velocity**를 중심에 두고, **Sentiment·Entity Prominence**(MVP), **Social Signals**(확장)까지 복합 스코어에 반영한다.

> **공식·가중치 출처 (중요)**: 이 가중합은 **학술 단일 출처가 없는 휴리스틱**이다. "볼륨·속도가 유효하다"는 근거는 벤치마크(RUBICS=볼륨, Bloomberg=속도)에서 왔고, **가중치 `wᵢ`는 초기 임의값**으로 실데이터 교정 전까지 확정값이 아니다(→ [§11](#11-미결-사항)).

### 6.1 스코어 계산

각 신호를 [0,1]로 정규화해 가중합한다. **가중치는 휴리스틱 초기값이며 실데이터 교정 대상**이다(→ [§11](#11-미결-사항)). 스케일이 다른 raw 값(예: volume 50, velocity 1.2)을 그대로 더하면 한 신호가 지배하므로 반드시 정규화한다.

```python
from dataclasses import dataclass

@dataclass
class ClusterScore:
    cluster_id: int
    representative_news_id: int   # = member_news_ids[0]
    member_news_ids: list[int]   # 클러스터 소속 기사 id (중심 근접순 정렬, §5.8)
    importance: float            # 복합 중요도 [0,1]

# 가중치 — 휴리스틱 초기값(교정 전). 학술 단일 출처 없음(§6.0).
W = {"volume": 0.4, "velocity": 0.3, "sentiment": 0.15, "entity": 0.15}

def score_cluster(
    cluster_size: int,
    max_cluster_size: int,
    prev_cluster_size: int,
    sentiment_intensity: float,   # |감성| [0,1] (LLM/FinBERT)
    entity_prominence: float,     # 코스피200·시총 기반 [0,1] (→ 03)
) -> float:
    volume_n   = cluster_size / max(max_cluster_size, 1)
    # velocity: 증가율 (첫 실행 prev=0 → 0), [0,1] 클리핑
    velocity_n = max(0.0, min((cluster_size - prev_cluster_size) / (prev_cluster_size + 1), 1.0))
    return (
        W["volume"]    * volume_n +
        W["velocity"]  * velocity_n +
        W["sentiment"] * sentiment_intensity +
        W["entity"]    * entity_prominence
    )   # Social Signals(구글 트렌드)는 확장 단계에 추가
```

> Sentiment·Entity Prominence는 MVP 포함, Social Signals는 확장. 첫 실행은 `prev_cluster_size=0`이라 velocity_n=0.

### 6.2 상위 이슈 선정·영속화

스코어링 결과는 `news_cluster` 테이블에 적재한다(클러스터당 1행 — 스키마는 [02 §8.3](./02-news-collection-design.md#83-news_cluster-테이블-클러스터링-산출물)). `embedding`은 `news`에 남고, 클러스터 식별·소속(`member_news_ids`)·`importance`만 분리 저장한다. 분석 단계는 이 테이블을 `importance` 내림차순으로 읽어 상위 이슈를 인계받는다.

```python
TOP_ISSUE_COUNT = 10  # 분석 파이프라인에 넘길 최대 이슈 수

async def persist_clusters(
    db: AsyncSession, run_date: date, scored_clusters: list[ClusterScore],
) -> list[int]:
    """클러스터를 news_cluster에 적재하고 상위 N개 대표 기사 ID 반환"""
    for c in scored_clusters:
        db.add(NewsCluster(
            run_date=run_date,
            representative_news_id=c.representative_news_id,
            member_news_ids=c.member_news_ids,
            size=len(c.member_news_ids),
            importance=c.importance,
        ))
    await db.commit()

    top = sorted(scored_clusters, key=lambda c: c.importance, reverse=True)
    return [c.representative_news_id for c in top[:TOP_ISSUE_COUNT]]
```

---

## 7. RAG 소스 준비 — ReportChunk 임베딩

사업보고서 청크(`report_chunks`)도 동일한 단계(EmbeddingClusterer)에서 임베딩한다.  
이 임베딩이 분석 파이프라인의 `ImpactAnalysisChain`에 기업 컨텍스트(`related_companies`)를 제공한다.

### 7.1 임베딩 대상

```python
# report_chunks 테이블의 embedding=NULL 레코드
SELECT id, corp_name, chunk_type, content
FROM report_chunks
WHERE embedding IS NULL
LIMIT 100;
```

### 7.2 LangChain PGVector 연동

```python
from langchain_postgres.vectorstores import PGVector
from langchain_google_vertexai import VertexAIEmbeddings

embeddings = VertexAIEmbeddings(model_name=settings.EMBED_MODEL)

vectorstore = PGVector(
    embeddings=embeddings,
    collection_name="report_chunks",
    connection=settings.DATABASE_URL,
)

# 분석 파이프라인에서 RAG 검색
def get_company_context(company_name: str, k: int = 3) -> str:
    docs = vectorstore.similarity_search(
        query=f"{company_name} 사업 현황 재무 요약",
        k=k,
    )
    return "\n".join([doc.page_content for doc in docs])
```

---

## 8. EmbeddingClusterer 설계

### 8.1 상태 (State)

```python
class EmbeddingClustererState(TypedDict):
    # 처리 통계
    news_embedded: int        # 임베딩 생성된 뉴스 수
    chunks_embedded: int      # 임베딩 생성된 ReportChunk 수
    duplicates_removed: int   # 유사도 중복 제거 수
    clusters_formed: int      # 형성된 클러스터 수
    top_issues: list[int]     # 분석 파이프라인에 넘길 기사 ID 목록
    errors: list[str]
```

### 8.2 노드 구성

```
[embed_news]  →  [deduplicate]  →  [cluster]  →  [score_and_select]
                                                        │
[embed_chunks] ──────────────────────────────────────┘
(병렬 실행)                                        [mark_analyzed]
```

| 노드 | 역할 |
|------|------|
| `embed_news` | `embedding=NULL` 뉴스 배치 임베딩 |
| `embed_chunks` | `embedding=NULL` ReportChunk 배치 임베딩 |
| `deduplicate` | cosine ≥ 0.95 중복 제거 |
| `cluster` | cosine ≥ 0.80 이슈 클러스터링 |
| `score_and_select` | 복합 중요도 스코어 계산 → `news_cluster` 적재 → 상위 10개 이슈 선정 |
| `mark_analyzed` | 선정된 기사 `is_analyzed=False` 확인 (분석 파이프라인 인계 준비) |

### 8.3 embed_news, embed_chunks 병렬 실행

두 임베딩 작업은 독립적이므로 병렬 처리한다.

```python
async def run(self) -> EmbeddingClustererState:
    # 임베딩 병렬 실행
    news_result, chunks_result = await asyncio.gather(
        self._embed_news(),
        self._embed_chunks(),
        return_exceptions=True,
    )
    # 클러스터링은 임베딩 완료 후
    await self._deduplicate()
    await self._cluster_and_select()
```

---

## 9. 임베딩 텍스트 정책 — 테이블별

| 테이블 | 임베딩 텍스트 | 이유 |
|--------|------------|------|
| `news` | `title` | 제목만 저장 (snippet 미저장), 주식 뉴스 제목은 키워드 밀도가 높아 클러스터링에 충분 |
| `disclosures` | `f"{title}. {content[:500]}"` | 공시 제목 + 본문 앞 500자 |
| `report_chunks` | `content` | 청크 본문 전체 (RAG 검색 정확도 우선) |

---

## 10. 구현 로드맵

| 단계 | 내용 | 산출물 | 선행 조건 |
|------|------|--------|---------|
| 1 | Neon pgvector 활성화 | `CREATE EXTENSION vector` | — |
| 2 | HNSW 인덱스 생성 | SQL 마이그레이션 | pgvector 활성화 |
| 3 | `news_embedder.py` 구현 (배치 임베딩) | `services/embedder/news_embedder.py` | Vertex AI 설정 |
| 4 | `deduplicator.py` 유사도 중복 제거 추가 | `services/preprocessor/deduplicator.py` | 임베딩 완료 |
| 5 | `cluster.py` 구현 (임계값 기반 클러스터링) | `services/embedder/cluster.py` | 임베딩 완료 |
| 6 | `report_embedder.py` 구현 (ReportChunk) | `services/embedder/report_embedder.py` | 사업보고서 텍스트 수집 완료 (`report_collector`) |
| 7 | LangChain PGVector 연동 | `app/llm/rag.py` | ReportChunk 임베딩 완료 |
| 8 | `EmbeddingClusterer` 조립 | `services/pipeline/embedding_clusterer.py` | 3~7 완료 |
| 9 | 통합 테스트 (실제 뉴스 100건) | — | 전체 파이프라인 완료 |

---

## 11. 미결 사항

| 항목 | 내용 | 결정 시점 |
|------|------|----------|
| **임베딩 모델 최종 확정** | **미확정** — 아래 하니스로 후보(gemini-embedding-001 / KURE-v1 / ko-sroberta baseline) 비교 후 결정 | Phase 2 시작 전 |
| **임베딩 텍스트 구성** | title 단독 시작. feed summary 결합(메모리 한정) 전환은 §2.2 실험으로 판단 | 클러스터링 구현 시 |
| **스코어 가중치(W) 교정** | 신호별 가중치(현재 0.4/0.3/0.15/0.15 휴리스틱)를 실데이터로 튜닝. 학술 출처 없음 | Phase 구현 후 |
| **Sentiment·Social 신호 통합** | Sentiment(LLM/FinBERT), Social(구글 트렌드 pytrends) 데이터 소스 연동 | MVP 이후 단계적 |
| 클러스터링 임계값 교정 | 실제 뉴스 100건으로 0.80·(mcs, min_samples) 적정 여부 테스트(§5.6) | Phase 구현 후 |
| TOP_ISSUE_COUNT | 상위 10개가 적절한지 서비스 기획과 조율 | 서비스 기획 논의 |
| `prev_cluster_size` 추적 방법 | velocity 계산을 위한 이전 클러스터 크기 저장 방법 | cluster.py 구현 시 |
| FinKRX 임베딩 버전 공개 여부 | LLM인지 임베딩 모델인지 확인, 공개 시 RAG 소스 임베딩에 적용 검토 | 모델 공개 후 |

### 임베딩 모델 비교 테스트 — 실행 하니스

**원칙: 동일 라벨셋·동일 다운스트림에서 모델만 바꿔 끝까지 돌려 결과표 한 장으로 비교한다.** 모델별로 차원·정규화가 다르므로 cosine 분리도만 보지 말고 클러스터링·RAG까지 동일 조건으로 측정한다.

```python
# 비교 대상 — 관리형 1 + 오픈소스 2 (baseline 포함)
CANDIDATE_MODELS = [
    "gemini-embedding-001",            # Vertex AI, 768 절단, MTEB Multilingual 1위 (관리형 후보)
    "nlpai-lab/KURE-v1",               # 한국어 검색 특화, MTEB-ko 1위 (1024)
    "jhgan/ko-sroberta-multitask",     # 현재 코드 기본값 — baseline
]

def embed_with(model_name: str, texts: list[str]) -> np.ndarray:
    """모델별 임베딩. Vertex(gemini) vs HuggingFace(KURE·ko-sroberta) 분기."""
    if model_name.startswith("gemini"):
        from langchain_google_vertexai import VertexAIEmbeddings
        emb = VertexAIEmbeddings(model_name=model_name)        # 768 절단 설정
    else:
        from langchain_huggingface import HuggingFaceEmbeddings
        emb = HuggingFaceEmbeddings(model_name=model_name)
    return np.array(emb.embed_documents(texts))

# 사전 준비: 같은이슈/다른이슈 쌍 50쌍씩 + 사람이 매긴 클러스터 정답(gold_labels)
def benchmark(model_name, news_texts, pos_idx, neg_idx, gold_labels):
    from sklearn.metrics import roc_auc_score, adjusted_rand_score
    X = embed_with(model_name, news_texts)
    S = cosine_similarity(X)

    # ① 분리도: 같은이슈 쌍 vs 다른이슈 쌍 cosine을 AUC로 (임계값 무관 단일 수치)
    pos = [S[i, j] for i, j in pos_idx]
    neg = [S[i, j] for i, j in neg_idx]
    auc = roc_auc_score([1]*len(pos) + [0]*len(neg), pos + neg)

    # ② 클러스터링: 동일 HDBSCAN 설정으로 돌려 사람 정답과 ARI 비교
    labels = cluster_news(X, min_cluster_size=2, min_samples=1)
    ari    = adjusted_rand_score(gold_labels, labels)
    sil    = evaluate_clustering(X, labels)["silhouette"]

    return {"model": model_name, "pair_auc": auc, "ari": ari, "silhouette": sil,
            "pos_mean": np.mean(pos), "neg_mean": np.mean(neg)}

results = [benchmark(m, news_texts, pos_idx, neg_idx, gold_labels) for m in CANDIDATE_MODELS]
# 결과표로 정렬 출력 → pair_auc·ari 최고 모델 채택
```

**③ RAG 검색 품질** (report_chunks 임베딩까지 영향): 동일 쿼리셋(예: `"삼성전자 반도체 수익성"`)으로 모델별 `similarity_search(k=5)` 후 관련 청크 **recall@5**를 사람이 채점해 비교.

**결과표 양식:**

| 모델 | pair_auc | ari | silhouette | pos_mean / neg_mean | RAG recall@5 |
|------|---------|-----|-----------|--------------------|--------------|
| gemini-embedding-001 | | | | | |
| KURE-v1 | | | | | |
| ko-sroberta (baseline) | | | | | |

> **판정**: `pair_auc`·`ari`가 baseline 대비 유의하게 높고, gemini와 KURE 격차가 작으면 **스키마 유지·인프라 통일 이점이 있는 gemini-embedding-001 채택**. KURE가 RAG recall에서 크게 앞서면 1024 전환 비용을 감수하고 KURE 채택 검토.

**모델 전환 비용 고려**: 모델 변경 시 `news`, `report_chunks` 테이블의 임베딩 전체 재계산 + (1024 모델은) `Vector` 차원 마이그레이션 필요.  
초기에 잘못 선택하면 대규모 재작업 발생 → **첫 번째 배포 전에 반드시 결정**.

---

## 참고 자료

- [`01-pipeline-orchestration-design.md`](./01-pipeline-orchestration-design.md) — EmbeddingClusterer 상태·에러 처리
- [Neon pgvector 공식 문서](https://neon.com/docs/extensions/pgvector)
- [LangChain PGVector](https://python.langchain.com/api_reference/postgres/vectorstores/langchain_postgres.vectorstores.PGVector.html)
- [Vertex AI Text Embedding API](https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings)
- [Gemini Embedding GA (Vertex AI·Gemini API, MTEB Multilingual 1위)](https://developers.googleblog.com/gemini-embedding-available-gemini-api/)
- [KURE (고려대 한국어 임베딩 모델)](https://github.com/nlpai-lab/KURE)
- [BGE-M3 (BAAI)](https://huggingface.co/BAAI/bge-m3)
- [FinKRX (원라인AI + 한국거래소, ACL 2025)](https://www.venturesquare.net/971372)
- [MTEB-ko-retrieval Leaderboard](https://huggingface.co/spaces/mteb/leaderboard)
- [한국어 임베딩 모델 벤치마크 비교](https://github.com/ssisOneTeam/Korean-Embedding-Model-Performance-Benchmark-for-Retriever)
