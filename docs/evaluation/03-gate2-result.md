# Gate 2 결과 — 클러스터링 알고리즘 (HDBSCAN vs 그래프)

> 생성 2026-06-21 21:49 · 골드셋 `goldset_2026-06-16.json` · 입력 `title_body`

| 모델 | HDBSCAN F1 | 그래프 best F1 | 그래프 best 임계 | 승자 |
| --- | --- | --- | --- | --- |
| jhgan/ko-sroberta-multitask | 0.610 | 0.585 | 0.80 | **HDBSCAN** |
| gemini-embedding-001 | 0.562 | 0.508 | 0.90 | **HDBSCAN** |

## 한계·주의

- 그래프는 임계 스윕의 best F1(알고리즘에 유리하게), HDBSCAN은 기본 파라미터 — 양쪽 정밀 튜닝은 §8.2.
- 코퍼스 100% 한국어 · 골드 라벨 Gemini 자동(스팟 검수 전).
