# 임베딩·클러스터링 기획서

**작성일** 2026-05-28  
**기획 범위** 전처리 완료 → 임베딩 생성 → 클러스터링 → 분석 파이프라인 인계  
**관련 문서**  
- [에이전트 오케스트레이션 아키텍처](./01-agent-orchestration-design.md)
- [전처리 기획서](./04-preprocessing-design.md)
- [기업 데이터 수집 기획서](./03-company-data-collection-design.md)

---

## 목차

- [1. 목적](#1-목적)
- [2. 임베딩 전략](#2-임베딩-전략)
- [3. pgvector 인덱스 설정](#3-pgvector-인덱스-설정)
- [4. 유사도 기반 중복 제거](#4-유사도-기반-중복-제거)
- [5. 클러스터링 알고리즘 비교 및 선택](#5-클러스터링-알고리즘-비교-및-선택)
- [6. 주요 이슈 선정 — 볼륨·속도 스코어](#6-주요-이슈-선정-—-볼륨·속도-스코어)
- [7. RAG 소스 준비 — ReportChunk 임베딩](#7-rag-소스-준비-—-reportchunk-임베딩)
- [8. EmbeddingClusteringAgent 설계](#8-embeddingclusteringagent-설계)
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
오늘의 주요 이슈 선정 (볼륨·속도 스코어)
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
| `news` | `preprocessed_at IS NOT NULL AND embedding IS NULL` | 전처리 완료 후 임베딩 |
| `report_chunks` | `embedding IS NULL` | 사업보고서 RAG 소스 준비 (전처리 불필요) |

---

## 2. 임베딩 전략

### 2.1 임베딩 모델 비교

장독대는 한국어 금융 뉴스를 주로 다루므로 모델 선택이 클러스터링·RAG 품질에 직접적인 영향을 미친다.  
**실제 데이터로 비교 테스트 후 최종 확정한다.** (→ 섹션 11 미결 사항 참조)

---

#### 후보 모델 전체 비교

| 모델 | 차원 | 운영 방식 | 한국어 | 금융 도메인 | MTEB-ko |
|------|------|---------|--------|-----------|---------|
| `text-multilingual-embedding-002` | 768 | Vertex AI (관리형) | ✅ | △ | 미공개 |
| `BAAI/bge-m3` | 1024 | 로컬 / HuggingFace | ✅✅ | △ | **최상위권** |
| `nlpai-lab/KURE-v1` | 768 | 로컬 / HuggingFace | ✅✅ | △ | **1위** (검색 특화) |
| `jhgan/ko-sroberta-multitask` | 768 | 로컬 | ✅✅ | △ | 중상위 |
| `FinKRX` | — | 미공개 | ✅✅ | ✅✅ | — |

---

#### 모델별 상세

**`BAAI/bge-m3`**
- 70개 언어 지원 다국어 모델. 한국어 MTEB retrieval F1 **0.35** (최상위권)
- 단일 모델로 dense·sparse·multi-vector 세 가지 검색 방식 지원
- HuggingFace 오픈소스, 로컬 GPU 또는 HuggingFace Inference API 사용
- 1024 차원 → `Vector(1024)` 로 스키마 변경 필요

**`nlpai-lab/KURE-v1`** (고려대학교 NLP&AI 연구실, 2024.12 공개)
- BGE-M3 기반으로 **한국어 검색에 특화** fine-tuning
- MTEB-ko-retrieval **1위** (Ko-StrategyQA 기준)
- 768 차원, 현재 스키마 변경 없이 사용 가능
- 한국어 multi-hop 질문 검색에서 강점 → 금융 뉴스 이슈 연결에 유리

**`jhgan/ko-sroberta-multitask`**
- `.env.example`에 이미 기재된 모델. 가장 많이 검증된 한국어 임베딩
- KorNLI + KorSTS로 학습. 한국어 STS(의미 유사도)에서 안정적
- 2021년 모델로 최신 모델 대비 성능 낮을 수 있음

**`text-multilingual-embedding-002`** (Vertex AI)
- Vertex AI 기존 인프라 재사용 가능. 추가 서버 불필요
- 한국어 포함 다국어 지원. MTEB-ko 공개 벤치마크 없어 품질 불확실
- API 비용 발생 (현재 기획서 기준 ~38~60회/일)

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
| 성능 한도 | 모델 품질 제한 | 한국어 특화 모델 사용 가능 |
| 유지보수 | 없음 | 모델 업데이트 관리 필요 |

> **초기 결정**: `text-multilingual-embedding-002`로 시작, 클러스터링 품질 검증 후 `KURE-v1` 또는 `bge-m3` 전환 여부 결정. 모델 변경 시 기존 임베딩 **전체 재계산** 필요하므로 초기에 신중히 선택.

---

#### 현재 잠정 선택

```
text-multilingual-embedding-002  ← 인프라 통일, 빠른 시작
        ↓ 클러스터링 품질 테스트 후
KURE-v1 또는 BGE-M3              ← 한국어 검색 품질 우선 시 전환
```

환경 변수:
```
EMBEDDING_MODEL=text-multilingual-embedding-002
EMBEDDING_DIM=768
```

---

### 2.2 임베딩 텍스트 구성

뉴스 메타데이터로 **제목만** 저장하므로 임베딩 입력도 title 단독으로 한다.

```python
def build_embed_text(title: str) -> str:
    return title
```

| 방식 | 장점 | 단점 |
|------|------|------|
| title만 **(채택)** | 저장 데이터 최소화, 저작권 안전 | 제목이 모호한 경우 클러스터링 품질 저하 |
| title + snippet | 맥락 풍부 | snippet 저장 필요 → 저작권 리스크 |

주식 뉴스 제목은 핵심 키워드 밀도가 높아 title만으로도 동일 이슈를 묶는 데 실용적으로 충분하다.  
(`"삼성전자 3분기 영업이익 9.2조"`, `"삼성전자 분기 실적 어닝서프라이즈"` → 같은 클러스터로 묶임)

---

### 2.3 배치 처리

Vertex AI API 요청 제한을 고려해 배치 단위로 처리한다.

```python
from vertexai.language_models import TextEmbeddingModel

EMBED_BATCH_SIZE = 50  # Vertex AI 최대 허용 배치 크기

async def embed_batch(texts: list[str]) -> list[list[float]]:
    model = TextEmbeddingModel.from_pretrained(settings.EMBEDDING_MODEL)
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

**② filter_confidence 임계값 (singleton 판별: 0.7)**

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
4. FilterChain 실행 → confidence 구간별 품질 평가 → singleton 임계값 도출
5. HDBSCAN 실행 → 사람이 결과 평가 → Silhouette 기준 역산
6. 도출된 값을 환경 변수에 반영
```

**현재 기획서 수치는 이 실험 전 시작점으로만 사용한다.**

---

### 5.4 Singleton 처리 — 중요한 단독 이슈 vs 노이즈

HDBSCAN이 `-1` (noise)로 분류한 기사는 두 가지 경우다.

```
noise (-1)
  ├── 중요한 단독 이슈 (단 한 개 언론사만 보도한 단독)
  └── 실제 노이즈 (금융 무관, 저품질 snippet)
```

**구분 기준 — 2단계 판별:**

#### 1단계: 소스 신뢰도

```python
# 주요 언론사 = 단독 보도여도 중요도 높음
AUTHORITATIVE_SOURCES = {"hankyung", "edaily", "einfomax"}  # 주요 증권 언론사

def is_authoritative_source(news: News) -> bool:
    return news.source in AUTHORITATIVE_SOURCES
```

#### 2단계: LLM FilterChain 신뢰도 점수

```python
# 이미 FilterChain을 통과한 기사 → filter_confidence 활용
def is_important_singleton(news: News, confidence_threshold: float = 0.7) -> bool:
    return (
        is_authoritative_source(news)
        or news.filter_confidence >= confidence_threshold
    )
```

**처리 방침:**

| 케이스 | 판별 | 처리 |
|--------|------|------|
| 주요 언론사 + filter_confidence ≥ 0.7 | 중요한 단독 이슈 | **단독 클러스터로 보존**, 분석 파이프라인 인계 |
| 주요 언론사 + filter_confidence < 0.7 | 단독 이슈 (중요도 낮음) | 보존하되 우선순위 낮음 |
| 소형 언론사 + filter_confidence < 0.5 | 노이즈 가능성 높음 | 분석 제외 (`is_analyzed=True` 처리) |

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

### 5.6 min_cluster_size 선정

임계값 기반이 아닌 HDBSCAN을 사용하므로 핵심 파라미터는 `min_cluster_size`다.

**선정 방법:**

```python
# 다양한 min_cluster_size 값으로 실험
for mcs in [2, 3, 4, 5]:
    labels = cluster_news(embeddings, min_cluster_size=mcs)
    metrics = evaluate_clustering(embeddings, labels)
    print(f"mcs={mcs}: n_clusters={metrics['n_clusters']}, "
          f"silhouette={metrics['silhouette']:.3f}, "
          f"noise_ratio={metrics['noise_ratio']:.2%}")
```

**기대 결과 패턴:**

| min_cluster_size | 효과 |
|----------------|------|
| 2 | 클러스터 많음, noise 적음, 작은 이슈도 클러스터화 |
| 3 | 균형점 (권장 시작값) |
| 5 | 클러스터 적음, noise 많음, 주요 이슈만 클러스터화 |

**초기값: `min_cluster_size=2`** — 같은 이슈를 2개 이상 언론사가 보도하면 클러스터 형성.  
Silhouette Score < 0.3이면 값을 올리고, noise 비율 > 60%이면 값을 내린다.

---

### 5.7 차원 축소 — 필요 여부 판단

**현재 상황:**
- `text-multilingual-embedding-002` / `KURE-v1`: **768차원**
- `BGE-M3`: **1024차원**
- HNSW 인덱스: 고차원에서도 효율적 (O(log n))
- 일별 처리 대상: ~1,900건 → 거리 행렬 1,900×1,900 = ~14MB

**결론: 768차원은 차원 축소 불필요.** HNSW가 충분히 처리한다.

**1024차원(BGE-M3) 사용 시 성능 문제 발생하면:**

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

### 5.8 대표 기사 선정

```python
def select_representative(cluster_ids: list[int], embeddings: np.ndarray) -> int:
    """클러스터 중심과 가장 가까운 기사 인덱스 반환"""
    cluster_embeddings = embeddings[cluster_ids]
    centroid = cluster_embeddings.mean(axis=0)
    sims = cosine_similarity([centroid], cluster_embeddings)[0]
    return cluster_ids[int(np.argmax(sims))]
```

---

**환경 변수:**
```
CLUSTER_MIN_CLUSTER_SIZE=2        # HDBSCAN min_cluster_size
CLUSTER_MIN_SAMPLES=1             # HDBSCAN min_samples
DEDUP_SIMILARITY_THRESHOLD=0.95   # 중복 제거 임계값
SINGLETON_CONFIDENCE_THRESHOLD=0.7 # 중요 단독 이슈 판별 기준
```

---

## 6. 주요 이슈 선정 — 볼륨·속도 스코어

클러스터링 완료 후 **오늘 분석할 이슈**를 선정한다.  
클러스터링 완료 후 클러스터 크기와 속도를 기반으로 최종 스코어를 계산한다.

### 6.1 스코어 계산

```python
from dataclasses import dataclass

@dataclass
class ClusterScore:
    cluster_id: int
    representative_news_id: int
    volume: int          # 클러스터 내 기사 수
    velocity: float      # 이전 수집 대비 증가율
    final_score: float

def score_cluster(
    cluster: list[int],
    prev_cluster_size: int = 0,
) -> float:
    volume = len(cluster)
    # velocity: 증가율 (이전 수집 기록 없으면 volume만 반영)
    velocity = (volume - prev_cluster_size) / (prev_cluster_size + 1)
    return volume * 0.6 + velocity * 0.4
```

> `prev_cluster_size`가 없는 첫 실행에서는 velocity=0으로 처리해 volume만 반영한다.

### 6.2 상위 이슈 선정

```python
TOP_ISSUE_COUNT = 10  # 분석 파이프라인에 넘길 최대 이슈 수

def select_top_issues(scored_clusters: list[ClusterScore]) -> list[int]:
    """스코어 상위 N개 클러스터의 대표 기사 ID 반환"""
    sorted_clusters = sorted(
        scored_clusters, key=lambda c: c.final_score, reverse=True
    )
    return [c.representative_news_id for c in sorted_clusters[:TOP_ISSUE_COUNT]]
```

---

## 7. RAG 소스 준비 — ReportChunk 임베딩

사업보고서 청크(`report_chunks`)도 동일한 에이전트에서 임베딩한다.  
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

embeddings = VertexAIEmbeddings(model_name=settings.EMBEDDING_MODEL)

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

## 8. EmbeddingClusteringAgent 설계

### 8.1 상태 (State)

```python
class EmbeddingClusteringAgentState(TypedDict):
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
| `score_and_select` | 볼륨·속도 스코어 계산 → 상위 10개 이슈 선정 |
| `mark_analyzed` | 선정된 기사 `is_analyzed=False` 확인 (분석 파이프라인 인계 준비) |

### 8.3 embed_news, embed_chunks 병렬 실행

두 임베딩 작업은 독립적이므로 병렬 처리한다.

```python
async def run(self) -> EmbeddingClusteringAgentState:
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
| 6 | `report_embedder.py` 구현 (ReportChunk) | `services/embedder/report_embedder.py` | dart-fss 수집 완료 |
| 7 | LangChain PGVector 연동 | `app/llm/rag.py` | ReportChunk 임베딩 완료 |
| 8 | `EmbeddingClusteringAgent` 조립 | `services/agents/embedding_clustering_agent.py` | 3~7 완료 |
| 9 | 통합 테스트 (실제 뉴스 100건) | — | 전체 파이프라인 완료 |

---

## 11. 미결 사항

| 항목 | 내용 | 결정 시점 |
|------|------|----------|
| **임베딩 모델 최종 확정** | 아래 비교 테스트 후 결정 | Phase 2 시작 전 |
| 클러스터링 임계값 교정 | 실제 뉴스 100건으로 0.80 적정 여부 테스트 | Phase 구현 후 |
| TOP_ISSUE_COUNT | 상위 10개가 적절한지 서비스 기획과 조율 | 서비스 기획 논의 |
| `prev_cluster_size` 추적 방법 | velocity 계산을 위한 이전 클러스터 크기 저장 방법 | cluster.py 구현 시 |
| FinKRX 임베딩 버전 공개 여부 | LLM인지 임베딩 모델인지 확인, 공개 시 RAG 소스 임베딩에 적용 검토 | 모델 공개 후 |

### 임베딩 모델 비교 테스트 방법

실제 장독대 뉴스 데이터로 다음 3개 모델을 비교한다.

```python
# 비교 대상
CANDIDATE_MODELS = [
    "text-multilingual-embedding-002",  # Vertex AI
    "BAAI/bge-m3",                      # 다국어, MTEB-ko 최상위
    "nlpai-lab/KURE-v1",                # 한국어 검색 특화, MTEB-ko 1위
]

# 평가 기준 1: 같은 이슈 기사 쌍 vs 다른 이슈 기사 쌍의 cosine similarity 분포
# → 좋은 모델: 같은 이슈 쌍은 높게(≥0.80), 다른 이슈 쌍은 낮게(<0.60) 분리
#
# 평가 기준 2: 클러스터링 결과 정성 평가
# → 100건 뉴스를 각 모델로 클러스터링 후, 클러스터가 실제로 같은 이슈를 묶는지 확인
#
# 평가 기준 3: RAG 검색 품질
# → "삼성전자 반도체 수익성" 쿼리로 report_chunks 검색 시 관련 청크가 상위에 오는지 확인
```

**모델 전환 비용 고려**: 모델 변경 시 `news`, `report_chunks` 테이블의 임베딩 전체 재계산 필요.  
초기에 잘못 선택하면 대규모 재작업 발생 → **첫 번째 배포 전에 반드시 결정**.

---

## 참고 자료

- [`01-agent-orchestration-design.md`](./01-agent-orchestration-design.md) — EmbeddingClusteringAgent 상태·에러 처리
- [Neon pgvector 공식 문서](https://neon.com/docs/extensions/pgvector)
- [LangChain PGVector](https://python.langchain.com/api_reference/postgres/vectorstores/langchain_postgres.vectorstores.PGVector.html)
- [Vertex AI Text Embedding API](https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/get-text-embeddings)
- [KURE (고려대 한국어 임베딩 모델)](https://github.com/nlpai-lab/KURE)
- [BGE-M3 (BAAI)](https://huggingface.co/BAAI/bge-m3)
- [FinKRX (원라인AI + 한국거래소, ACL 2025)](https://www.venturesquare.net/971372)
- [MTEB-ko-retrieval Leaderboard](https://huggingface.co/spaces/mteb/leaderboard)
- [한국어 임베딩 모델 벤치마크 비교](https://github.com/ssisOneTeam/Korean-Embedding-Model-Performance-Benchmark-for-Retriever)
