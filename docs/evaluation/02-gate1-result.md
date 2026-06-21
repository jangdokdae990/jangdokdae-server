# Gate 1 결과 — 모델 × 입력 구성 (한국어 클러스터링 쌍별 F1)

> 생성 2026-06-21 20:17 · 골드셋 `goldset_2026-06-16.json` (411건, gold 307클러스터)

## 순위 (쌍별 F1 내림차순)

| 순위 | 모델 | 입력 | 쌍별 F1 | P | R | ARI | NMI |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | jhgan/ko-sroberta-multitask | title_body | **0.610** | 0.488 | 0.812 | 0.609 | 0.952 |
| 2 | intfloat/multilingual-e5-large | title_body | **0.588** | 0.486 | 0.743 | 0.586 | 0.958 |
| 3 | gemini-embedding-001 | title | **0.583** | 0.501 | 0.697 | 0.582 | 0.953 |
| 4 | BAAI/bge-m3 | title_body | **0.580** | 0.512 | 0.670 | 0.579 | 0.954 |
| 5 | gemini-embedding-001 | title_body | **0.562** | 0.511 | 0.625 | 0.561 | 0.952 |
| 6 | BAAI/bge-m3 | title | **0.555** | 0.460 | 0.701 | 0.554 | 0.950 |
| 7 | intfloat/multilingual-e5-large | title | **0.532** | 0.463 | 0.625 | 0.530 | 0.950 |
| 8 | jhgan/ko-sroberta-multitask | title | **0.522** | 0.441 | 0.640 | 0.520 | 0.949 |

## 유의성 (서브샘플 부트스트랩, 300라운드·80%)

재현: `python -m evaluation.significance --goldset scripts/data/goldset_2026-06-16.json`

| 조합 | F1 평균 | 95% CI | 1위 확률 |
| --- | --- | --- | --- |
| ko-sroberta · title_body | 0.609 | [0.559, 0.658] | **67.7%** |
| e5-large · title_body | 0.587 | [0.522, 0.657] | 16.7% |
| gemini · title | 0.584 | [0.524, 0.633] | 9.3% |
| bge-m3 · title_body | 0.580 | [0.528, 0.638] | 3.3% |

## 결론

- **입력 구성**: title 평균 0.548 vs title_body 0.585 → **title_body 채택**. ko-sroberta 기준 title_body(0.609) vs title(0.524) 격차 0.085로 노이즈를 크게 상회 → 통계적으로 견고.
- **모델**: **ko-sroberta 채택**(+title_body). 1위 확률 67.7%로 최선의 베팅이고, 운영성(768차원=현 `Vector(768)` 스키마 마이그레이션 불필요·로컬 실행=API 비용·쿼터 0·한국어 특화)에서도 우위. **단 상위 3~4개 95% CI가 겹쳐 통계적 우위는 미확정** — spec 폴백 규칙(ΔF1 미미 시 운영성으로 결정)에 따른 선택임을 명시한다.

## 한계·주의

- 코퍼스 100% 한국어 — 교차언어 평가 미적용(영어 데이터 부재).
- 골드 라벨은 Gemini 자동 라벨(사람 스팟 검수 전). 모델 선정은 운영성 기준이라 라벨 미세 변동에 둔감하나, 엄밀화 시 검수 후 재실행(임베딩 캐시로 수 초).
- HDBSCAN 기본 파라미터 — noise ~30% vs 실제 단독비율 65%로 과병합(precision 낮음), 파라미터 스윕은 §8.2.
- e5 계열은 query/passage prefix 미적용(원문 그대로 임베딩) — 동일 조건 비교 목적.
