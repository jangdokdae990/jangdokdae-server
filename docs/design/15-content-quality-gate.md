# 15. 콘텐츠 발행 품질 게이트 · term_spans 본문 정합

> **작성자** Kim minkyoung · **작성일** 2026-06-22
>
> **범위** 발행 가치 없는 issue_docent 콘텐츠(원문 무내용으로 모든 head가 honest-blank)를 생성·분석 단계에서 차단하고, 본문에 없는 용어가 `term_spans`에 박히는 버그를 막는 변경. 콘텐츠 생성 흐름은 [10](./10-content-pipeline-implementation.md), issue_docent 모델은 [13](./13-issue-docent-tagging-and-title.md)을 따른다.
>
> **핵심 결정**: 두 게이트(생성 후 honest-blank 카운터 + 분석 전 본문 부족) → **needs_review 격리**(드롭 아님) · term_spans는 content_heads 본문에 실제 등장하는 term만 보존 · 임계값은 프로덕션 스캔 실측으로 결정.

---

## 목차

- [1. 문제](#1-문제) · [2. 스캔 근거](#2-스캔-근거) · [3. 두 게이트](#3-두-게이트)
- [4. term_spans 본문 정합](#4-term_spans-본문-정합) · [5. 임계값](#5-임계값) · [6. 기존 데이터 리메디에이션](#6-기존-데이터-리메디에이션) · [7. 참고 자료](#7-참고-자료)

## 1. 문제

issue_docent #159는 OPINION(전문가 평가)으로 분류됐으나 원문에 목표주가·투자의견이 없어 4개 head가 모두 "이 기사는 …담고 있지 않습니다"(honest-blank)로 채워졌다 — **발행 가치 없는 콘텐츠가 그대로 저장**됐다. 기존 게이트는 ① relevance 필터(비투자성 skip) ② OPINION 1단 가드(head1 종목명) ③ confidence 임계 needs_review뿐이라, **본문 무내용/honest-blank를 막지 못했다**. #159는 company_tag가 없어(DS자산운용=운용사) OPINION 가드가 공허 통과했다.

추가로, LLM이 `term_tags`엔 있으나 본문엔 쓰지 않은 용어까지 `term_spans`로 출력해, **content_heads에 없는 용어가 issue_docent.term_spans에 저장**되는 버그가 있었다(프런트가 본문에 없는 용어를 하이라이트).

## 2. 스캔 근거

운영 DB `issue_docent` 78행을 honest-blank 문구로 스캔한 결과(read-only):

| head 4개 중 blank 수 | 행 수 |
|---|---|
| 0 | 65 |
| 1 | 11 |
| 2 | 1 (#107 "LIG디펜스 목표가↑") |
| 4 | 1 (#159 "DS의 투자법") |

1개 blank 11행은 대체로 정상(OPINION 괴리율 단일 honest-blank). 따라서 **2개 이상**을 발행 의심으로 잡으면 #159·#107만 격리되고 정상 11행은 유지된다.

## 3. 두 게이트

처리 방식은 두 게이트 모두 **needs_review=True 격리**(is_published=False 유지) — 드롭이 아니라 검수 큐로 보내 사람이 구제할 수 있게 한다.

- **생성 후 honest-blank 게이트**: `ContentGenerator.generate_with_guard`가 OPINION 가드에 더해, head 답변 중 honest-blank 문구를 포함한 수가 `max_blank_heads` 이상이면 `review=True`. 원문에 내용이 없으면 재생성해도 무의미하므로 재생성 없이 격리만 한다. honest-blank 판정은 `frames.count_blank_heads`(`BLANK_PHRASES` 스캐너, 금지표현 `find_forbidden_words`와 같은 패턴).
- **분석 전 본문 부족 사전 게이트**: 대표 기사 본문이 `min_source_body_chars` 미만이면 생성은 honest-blank로 수렴하므로, 그래프의 `classify_node`가 `source_insufficient`를 표식하고 `route_after_classify`가 enrich·generate(LLM 호출)를 건너뛴다. `NewsAnalyzer`는 이를 relevance skip과 구분해 news_analysis를 `needs_review=True`로 적재하고(issue_docent 미적재), `low_source` 카운터로 러너 보고에 노출한다.

## 4. term_spans 본문 정합

`ContentGenerator.generate`가 `term_spans`를 중복 제거 전에 **본문 정합 필터**(`_filter_term_spans_in_body`)로 거른다 — content_heads 답변을 결합한 본문에 `term`이 실제 등장하는 span만 남긴다. 드롭이 있으면 cluster_id·제거된 term을 경고 로그로 남긴다. 생산자는 `generate` 한 곳뿐이라 `_persist`→`save_issue_docent` 전달 경로는 그대로다.

## 5. 임계값

`app/config.py`:
- `max_blank_heads = 2` — head 4개 중 honest-blank가 이 수 이상이면 needs_review(스캔상 #159=4·#107=2 격리, 단일-blank 11행 유지).
- `min_source_body_chars = 200` — 대표 기사 본문이 이 미만이면 원문 부족으로 간주.

## 6. 기존 데이터 리메디에이션

게이트·필터는 앞으로 생성되는 콘텐츠에만 적용되므로, 이미 저장된 행은 1회성 스크립트(`scripts/remediate_issue_docent.py`)로 **규칙 기반**(id 하드코딩 없이) 정리한다: 본문 미등장 term_spans 제거 + `count_blank_heads >= max_blank_heads`인 행 needs_review=True. dry-run으로 변경을 미리 확인한 뒤 적용한다.

## 7. 참고 자료

- [10. 콘텐츠 파이프라인 구현 설계](./10-content-pipeline-implementation.md) · [13. Issue Docent 태깅·제목](./13-issue-docent-tagging-and-title.md)
- `services/analyzer/content_generator.py` · `services/analyzer/frames.py` · `app/llm/graph.py` · `services/pipeline/news_analyzer.py`
