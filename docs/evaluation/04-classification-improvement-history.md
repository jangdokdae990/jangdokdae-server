# 분류 개선 반영 전후 히스토리 (OPINION 우선 · 거시 가이드 · relevance 필터)

> **작성자** Lee subeom (비파괴 A/B 비교 [scripts/compare_classify_improvement.py](../../scripts/compare_classify_improvement.py) + 운영 반영 기록) · **작성일** 2026-06-18 (운영 반영 2026-06-19)
>
> **범위** [01 프레임 커버리지](./01-frame-coverage-verification.md)·[03 단계별 평가](./03-pipeline-stage-evaluation.md)의 "결론·제안"을
> 실제 프롬프트/스키마/파이프라인에 **반영**하고, ① 효과를 비파괴 A/B로 측정(§3) → ② **라이브 DB에 실제 적용**(§3.4)한 기록.
> A(Before)=기존 적재 분류, B(After)=개선 분류기. 대상 = 적재 86건(size≥2, run_date 2026-06-15·06-17).

## 목차
1. [한눈에 보기](#1-한눈에-보기)
2. [무엇을 바꿨나](#2-무엇을-바꿨나)
3. [전후 비교 결과](#3-전후-비교-결과)
4. [한계·후속](#4-한계후속)
5. [참고 자료](#5-참고-자료)

---

## 1. 한눈에 보기

eval/01이 짚은 세 과제(① OPINION 과소검출 ② 거시지표 경계 ③ 비투자성 잡뉴스)를 분류기에 반영했고,
재분류 A/B(n=86)에서 **세 과제 모두 의도대로 교정됨**을 확인한 뒤, **2026-06-19 라이브 DB에 적용 완료**했다(§3.4).

| 효과 | 건수 (n=86) | 비고 |
|------|-----|------|
| **OPINION 회복**(비OPINION→OPINION) | **8** | eval/01 §3.2-a가 지목한 5건 전부 + 3건 추가. 그중 7건은 콘텐츠 유지, 1건(25)은 비투자성으로 동시 필터 |
| **거시 교정**(EARNINGS→TREND) | **4** | eval/01 §3.2-b가 지목한 4건(2·26·289·297) 전부 교정 |
| **relevance 필터**(비투자성=false) | **8** | eval/01 §3.1 "7개 밖" 6건 전부 + 신규 2건(프로모션·칼럼) → 콘텐츠 생성 skip |
| (부수) frame 변화 총계 | 24 | 위 교정 + 일반 재분류 변동 |
| (부수) OPINION 이탈(OPINION→타) | 2 | 경미한 역방향 변화(§4) |

→ **반영한 개선이 표적했던 오류를 정확히 줄였다.** 특히 relevance 필터는 eval/01의 결손 범주 6건을 **빠짐없이** 잡았다.

## 2. 무엇을 바꿨나

분류 1콜(호출 A) 안에서 처리되도록, 프롬프트와 스키마·그래프만 손봤다(생성 단계·백필은 불변).

| 항목 | 변경 | 파일 |
|------|------|------|
| OPINION 우선 규칙 | "기사 주체가 전문가의 평가·의견·목표가·투자전략이면 소재(신제품·업황·정책)와 무관하게 OPINION" | [prompts/news_classify.yaml](../../prompts/news_classify.yaml) |
| 거시 가이드 | "물가·통계·환율 등 거시지표는 EARNINGS 아닌 TREND/POLICY 우선" | 〃 |
| 투자 관련성 게이트 | `is_investment_relevant` 판정 지시 + 출력 스키마/예시(비투자성 false 예시 추가) | 〃 + [schemas.py](../../services/analyzer/schemas.py) |
| relevance skip 분기 | classify 후 **조건부 엣지** — false면 enrich·generate 건너뛰고 종료 | [app/llm/graph.py](../../app/llm/graph.py) |
| skip 적재 | content 없으면 분류만 적재(`is_investment_relevant=false`)하고 `issue_docent` 생략 | [news_analyzer.py](../../services/pipeline/news_analyzer.py) |
| 컬럼·마이그레이션 | `news_analysis.is_investment_relevant`(bool, 기본 true) — 리비전 `e8f1a2b3c4d5` | [news_analysis.py](../../app/db/orm_models/news_analysis.py)·[queries.py](../../app/db/queries.py) |

**미반영(범위 외)**: 검수 신호 재설계·enrich 적중 계측·generate 재시도·기업 미해소 라벨(eval/03 §4 P2~P3),
요약-우선([02](./02-summary-first-comparison.md)) — 아직 실험 단계라 프로덕션 미반영.

## 3. 전후 비교 결과

### 3.1 OPINION 회복 (8건)
전문가 의견·리포트·운용사 인터뷰가 소재 frame으로 잘못 분류되던 것이 OPINION으로 교정됐다.

| cluster | A→B | 제목 |
|---|---|---|
| 21 | PRICE→OPINION | [MK시그널] ST마이크로 수익률 170% 돌파 |
| 302 | PLAN→OPINION | 파로스아이바이오, 기술이전 논의…(클릭 e종목) |
| 310 | PLAN→OPINION | "좋은 기업은 주가가 따라온다"…DS의 투자법 |
| 313 | POLICY→OPINION | 6만전자 쓸어담은 '한국의 버핏'… |
| 319 | TREND→OPINION | [생생한 주식쇼] 중동 재건 수혜주 분석 |
| 293 | TREND→OPINION | 딜로이트 "내부회계 지적 기업 80%…" |
| 329 | TREND→OPINION | 호르무즈 정상화까지 수개월…"유가 단기 급락 없다" |
| 25 | TREND→OPINION | "노후 준비, 자산보다 현금흐름이 핵심" (※동시에 비투자성 필터 → skip) |

### 3.2 거시 교정 (4건) — EARNINGS→TREND
거시 통계를 개별 기업 실적으로 오인하던 경계가 바로잡혔다: [2] 독일 도매물가 · [26] 증권사 업황 · [289] 기관 PEF 투자규모 · [297] 캐나다 주택판매.

### 3.3 relevance 필터 (8건) — 콘텐츠 생성 skip
eval/01 §3.1의 "7개 밖" 6건(1·5·8·13·22·286)을 **전부** 포착 + 신규 2건([6] KB카드 프로모션 · [25] 노후 칼럼).
이들은 분석 시 분류만 남고 `issue_docent`(콘텐츠)는 적재되지 않는다 → **PLAN 과부하·노이즈가 원천 차단**된다.

> 운영 반영 시: 86건 중 8건(약 9%)이 콘텐츠 생성에서 제외돼 그만큼 생성 LLM 호출·검수 부담도 준다.

### 3.4 운영 반영 결과 (as-run, 2026-06-19)
A/B로 확인 후 **라이브 Neon DB에 실제 적용**했다 — ① `news_analysis.is_investment_relevant` 컬럼을 직접
`ALTER TABLE ... ADD COLUMN ... DEFAULT true`로 추가(라이브 alembic이 로컬에 없는 `fa6e579bc7dc`로 분기돼
`alembic upgrade` 불가 → 직접 ALTER, additive·안전), ② 적재 86건을 `scripts.run_analysis --rerun`(배치)으로 재분석.
(재실행 중 일시 오류로 누락된 8건은 `--cluster-id` 타겟 재실행으로 복구.)

| 지표 | 반영 전 | 반영 후(실DB) |
|------|-----|-----|
| `news_analysis` | 86 | 86 |
| `issue_docent` | 86 | **78** (비투자성 8건 콘텐츠 미생성) |
| `is_investment_relevant=false` | (없던 컬럼) | **8** |
| frame: EARNINGS | 4 | **0** (거시 4건 → TREND) |
| frame: TREND | 8 | **12** (+4, 거시 교정) |
| frame: OPINION | 12 | **14** (+2, 과소검출 회복) |
| frame: PRICE | 10 | **7** (−3, 원인 frame으로 이동) |
| frame: PLAN / POLICY / INCIDENT | 34 / 7 / 10 | 36 / 7 / 10 |

→ A/B 예측(거시 EARNINGS→TREND, OPINION 회복, 비투자성 8건 필터)이 실DB에 그대로 반영됐다. 정합성 확인:
비투자성인데 `issue_docent`가 있는 행 0건, `issue_docent` 78 = `is_investment_relevant=true` 78.

## 4. 한계·후속

- **OPINION 이탈 2건**(경미): [30] 메모리 소부장 순번·[333] 한전 종전 모멘텀이 OPINION→TREND로 바뀌었다(둘 다 투자 관련 유지).
  목표가·투자의견이 약한 시황/특징주성 글이라 경계 사례 — 순효과는 회복 8 vs 이탈 2로 크게 개선.
- **일반 재분류 변동**: scope 5·sector 15·companies 19 변화는 표적 개선 외 LLM 재분류 변동(프롬프트 변경+비결정성 혼재). 표적 지표(OPINION·거시·relevance)와 분리해 해석.
- **운영 반영 완료(§3.4)**: §3은 비파괴 A/B(측정), §3.4는 라이브 DB 실제 적용(as-run)이다. 컬럼은 alembic 분기로 직접 ALTER했고,
  마이그레이션 파일 `e8f1a2b3c4d5`는 repo 기록으로 유지(alembic 계보 정합은 후속 — doc 11 §7).
- **요약-우선 미반영**: [02](./02-summary-first-comparison.md)는 frame 21%·기업 39% 변동으로 아직 검증 단계 → 이번 반영에서 제외.

## 5. 참고 자료

- 근거 평가: [01-frame-coverage-verification.md](./01-frame-coverage-verification.md)(§3·§4·§5) · [03-pipeline-stage-evaluation.md](./03-pipeline-stage-evaluation.md)(§4)
- 설계 반영: [10-content-pipeline-implementation.md](../design/10-content-pipeline-implementation.md)(§2·§5·§7.1·§8) · [11-analysis-run-and-backfill.md](../design/11-analysis-run-and-backfill.md)(§7·§8)
- 비교 스크립트: [scripts/compare_classify_improvement.py](../../scripts/compare_classify_improvement.py) · 상세 `/tmp/classify_improvement.json`
- 코드: [prompts/news_classify.yaml](../../prompts/news_classify.yaml) · [services/analyzer/schemas.py](../../services/analyzer/schemas.py) · [app/llm/graph.py](../../app/llm/graph.py) · [services/pipeline/news_analyzer.py](../../services/pipeline/news_analyzer.py)
