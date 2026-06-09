# 임베딩 모델 비교 결과

> **작성자** mkim · **작성일** 2026-06-09
>
> **범위** 설계 [05 §2.1·§11](../design/05-embedding-clustering-design.md)의 "임베딩 모델 미확정"을 풀기 위한 1차 비교 결과
>
> **관련 문서** [임베딩·클러스터링 기획서](../design/05-embedding-clustering-design.md)

---

## 1. 목적

설계 05는 임베딩 모델을 **미확정**으로 두고, 첫 배포 전에 실데이터로 후보를 비교해 확정하라고 명시한다(§11). 모델을 바꾸면 임베딩 전체 재계산 + (1024 모델은) 차원 마이그레이션이 따르므로 초기 결정이 중요하다.

이 문서는 **실제 수집된 장독대 뉴스 387건**으로 후보 3종을 비교한 **1차(비지도) 결과**를 정리한다.

> **이 결과는 방향성 근거이지, 설계 §11의 최종 판정은 아니다.** 라벨(정답)이 없어 `pair_auc`·`ARI`는 측정하지 못했고, `report_chunks`가 비어 있어 RAG recall@5도 미측정이다. 한계는 §6 참조.

---

## 2. 실험 설정

| 항목 | 값 |
|------|-----|
| 데이터 | Neon `news` 테이블 `is_filtered=false` 제목 387건 (실제 수집분) |
| 입력 | 제목 단독 (설계 §2.2 — title only) |
| 비교 방식 | 비지도 — 모델별 임베딩 → 동일 HDBSCAN → 지표·샘플 클러스터 비교 |
| 클러스터링 | HDBSCAN `min_cluster_size=2`, `min_samples=1`, precomputed cosine, `eom` (설계 §5.2) |
| Vertex task type | `CLUSTERING` (gemini만 해당) |
| 도구 | [`scripts/embedding_compare_unsupervised.py`](../../scripts/embedding_compare_unsupervised.py) |

**비교 후보 3종** (설계 §11):

| 모델 | 운영 | 차원 | 비고 |
|------|------|------|------|
| `gemini-embedding-001` | Vertex AI (관리형) | 768 (MRL 절단) | 관리형 후보, MTEB Multilingual 1위 |
| `nlpai-lab/KURE-v1` | HuggingFace (로컬) | 1024 | 한국어 검색 특화, MTEB-ko 1위 |
| `jhgan/ko-sroberta-multitask` | HuggingFace (로컬) | 768 | 현재 코드 기본값 — baseline |

---

## 3. 정량 결과

387건 기준:

| 모델 | 차원 | 클러스터 수 | noise 비율 | silhouette |
|------|------|------------|-----------|-----------|
| **gemini-embedding-001** | 768 | 89 | **31.5%** | **0.515** |
| nlpai-lab/KURE-v1 | 1024 | 90 | 34.4% | 0.460 |
| jhgan/ko-sroberta-multitask | 768 | 85 | 38.5% | 0.484 |

- **gemini가 silhouette 최고·noise 최저로 양쪽 1위.**
- 참고: 동일 실험을 100건으로 먼저 돌렸을 때 silhouette은 KURE 0.316 / ko-sroberta 0.300이었다. 387건으로 늘리자 세 모델 모두 구조가 뚜렷해졌고(0.46~0.52) gemini가 앞섰다 — 표본이 클수록 차이가 드러난다.
- silhouette은 금융 뉴스 특성상 0.2~0.35도 정상이라 했으나(설계 §5.3), 제목 단독·받아쓰기 다수인 이 코퍼스에선 그보다 높게 나왔다.

> silhouette은 **각 모델의 자기 임베딩 공간**에서 계산되므로 모델 간 절대 비교는 약하다. noise 비율(클러스터에 못 들어간 비율)과 아래 정성 분석을 함께 봐야 한다.

---

## 4. 정성 분석 (샘플 클러스터)

### gemini-embedding-001 — 가장 깔끔

같은 이슈를 정확히 묶고 오염이 가장 적다.

- **삼성전자 시총 2000조**(9건) — 속보·해설 변형을 한 덩어리로.
- **증권사 상품별 정확 분리** — NH IMA 완판 / 한투 엔화RP / 유안타 펀드 500억을 **각각 다른 클러스터**로.
- 삼성 KODEX ETF 200조(6건) 깔끔. 가상자산 기사들도 한 테마로 묶음.

### nlpai-lab/KURE-v1 — 좋지만 테마가 약간 느슨

- 핵심 이슈(삼성 시총 2000조 8건, 한투 엔화RP, ETF AUM)는 잘 묶음.
- 다만 테마 단위로 넓게 묶는 경향: "코람코 해외 인프라"에 미코 LNG·엔케이텍 수소트램이 섞이고, "생생한 주식쇼"(프로그램명)로 묶으며 이질 주제 혼입.

### jhgan/ko-sroberta-multitask (baseline) — 템플릿 오묶음 약점

- 이슈 묶기는 되지만 **헤드라인 형식으로 잘못 묶는 약점**이 보임: `[더밸류 브리핑]` 5건을 내용이 아니라 **제목 템플릿**으로 한 클러스터에 묶음(서로 다른 증권사 소식).
- AI반도체 클러스터에 "월가 AI 거품" 같은 이질 기사 혼입.

---

## 5. 결론 — gemini-embedding-001 권장

설계 §11의 판정 기준("`pair_auc`·`ARI`가 baseline 대비 높고 gemini·KURE 격차가 작으면 gemini 채택")과 일치하는 방향이다.

| 근거 | 내용 |
|------|------|
| **정량** | silhouette 최고(0.515), noise 최저(31.5%) |
| **정성** | 같은 이슈를 가장 정확히 분리, 템플릿/테마 오묶음 최소 |
| **스키마** | 768 차원 → 현재 `Vector(768)` 그대로 (KURE 1024는 스키마 변경 + 전체 재계산) |
| **인프라** | Vertex/Gemini로 LLM 분석과 백엔드 통일, 별도 GPU 서버 불필요 |

확정 시 변경 사항:
```
EMBED_MODEL=gemini-embedding-001
EMBED_DIM=768
```
Vertex task type은 용도별로 분기한다 — 뉴스 클러스터링 `CLUSTERING`, RAG 청크 `RETRIEVAL_DOCUMENT`, 검색 쿼리 `RETRIEVAL_QUERY`([`embedding_client.py`](../../services/embedder/embedding_client.py)).

---

## 6. 한계와 다음 단계

**이번 결과의 한계:**
1. **라벨 없음** — `pair_auc`·`ARI`(사람 정답 대비) 미측정. silhouette은 약한 비교.
2. **RAG recall 미측정** — `report_chunks`가 비어 있어 사업보고서 검색 품질(§11 ③)을 못 쟀다. KURE의 강점(장문 한국어 검색)이 평가에서 빠졌다.
3. 단일 시점·제목 단독 코퍼스 — 다른 날·다른 분포에서 재확인 필요.

**확정 전 권장 검증(설계 §11 정식 하니스 — 이미 구현됨):**
- 같은이슈/다른이슈 쌍 50쌍씩 + gold 클러스터를 라벨링해 [`scripts/embedding_model_benchmark.py`](../../scripts/embedding_model_benchmark.py)로 `pair_auc`·`ARI` 측정.
- `report_chunks` 적재 후 동일 쿼리셋으로 RAG recall@5 비교 → KURE 강점 재확인.

---

## 7. 재현 방법

```bash
# (gemini 포함하려면 먼저) 서비스 계정 키를 .env GOOGLE_APPLICATION_CREDENTIALS에 지정
uv run python -m scripts.embedding_compare_unsupervised 387   # 비지도 비교 (이 문서)
uv run python -m scripts.embedding_model_benchmark            # 정식 라벨 벤치마크 (라벨셋 필요)
```
