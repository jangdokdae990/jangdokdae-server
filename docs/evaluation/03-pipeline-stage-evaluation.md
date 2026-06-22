# 분석 파이프라인 단계별 수행 평가 (fetch → classify → enrich → generate → 백필 → persist)

> **작성자** Lee subeom (단계별 평가, 적재 데이터·실행 로그 기반) · **작성일** 2026-06-18
>
> **범위** "DB 클러스터 → 분류 → 콘텐츠 생성 → DB 저장"([10](../design/10-content-pipeline-implementation.md)·[11](../design/11-analysis-run-and-backfill.md)) 분석 단계의 **각 하위 과정이 의도대로 수행됐는지**를,
> 실제 적재된 `news_analysis`·`issue_docent` 86건(size≥2, run_date 2026-06-15·06-17)과 실행 로그를 증거로 평가한다.
> 분류 체계 적합성은 [01](./01-frame-coverage-verification.md), 요약-우선 실험은 [02](./02-summary-first-comparison.md)에서 별도로 다룬다.

## 목차
1. [한눈에 보기 (단계별 판정)](#1-한눈에-보기-단계별-판정)
2. [평가 방법·표본](#2-평가-방법표본)
3. [단계별 평가](#3-단계별-평가)
4. [종합·개선 우선순위](#4-종합개선-우선순위)
5. [참고 자료](#5-참고-자료)

---

## 1. 한눈에 보기 (단계별 판정)

| 단계 | 판정 | 핵심 근거 |
|------|------|-----------|
| ① 본문 fetch | ✅ 양호 | URL fetch 81회 중 실패 ~4–6, 폴백 체인으로 title-only 전락 거의 0 |
| ② classify (호출 A) | ⚠️ 동작하나 품질 과제 | 분포는 정상이나 **confidence 과신**(0.9가 86건 중 72), **OPINION 과소검출**·**PLAN 과부하**(→[01](./01-frame-coverage-verification.md)) |
| ③ enrich (OPINION 현재가) | ⚠️ 동작·관측성 부족 | OPINION 13건에 대해 노드 실행되나 **적중/blank 여부가 미저장** → 계측 불가 |
| ④ generate (호출 B) | ✅ 양호 | content_heads **4-head 100%**(86/86), hook 빈값 0, 생성 실패 1/54(일시) |
| ⑤ 엔티티·섹터 백필 | ✅ 양호 | **섹터 107/107=100% 해소**(GICS 정합 검증), 기업 124/239=52%(미상장·해외 제외 — 설계상 정상) |
| ⑥ persist | ✅ 양호 | `news_analysis` 86 = `issue_docent` 86 = 분석 클러스터 수, ON CONFLICT 멱등 |

**총평**: 골격(fetch→생성→저장)과 백필·persist는 **신뢰성 있게 수행**된다. 남은 과제는 코드 결함이 아니라
**분류 품질(②)**과 **보강 단계의 관측성(③)** 이다 — 둘 다 프롬프트·계측 보강으로 해결 가능.

## 2. 평가 방법·표본

- **표본**: 분석 전용 러너([scripts/run_analysis.py](../../scripts/run_analysis.py)) `--min-size 2 --limit 0`로
  적재한 size≥2 클러스터 **86건**(run_date 2026-06-15: 32 · 2026-06-17: 54). 배치 결과 **완료 53 / 실패 1 / 스킵 0**(신규 54건 기준, cluster 300 일시 실패).
- **증거**: ① 적재 데이터 직접 집계(`news_analysis`·`issue_docent` 분포·길이·백필 매칭률), ② 실행 로그
  (`/tmp/run_analysis_expand.log` — fetch 성패·생성 실패), ③ 분류 품질은 독립 재판정 [01](./01-frame-coverage-verification.md) 재인용.
- **한계**: enrich 적중률·generate 가드 재생성 횟수는 DB에 별도 저장되지 않아 일부는 정성 평가. size=1 단건은 제외.

## 3. 단계별 평가

### ① 본문 fetch — ✅ 양호
대표기사부터 중심근접순으로 본문을 시도하고 실패 시 다음 멤버로 폴백([fetch_first_available](../../services/analyzer/article_fetcher.py), [10 §8](../design/10-content-pipeline-implementation.md)).
- 확대 배치(54클러스터) 로그: 기사 GET **81회 중 fetch 실패 ~4–6건**(주로 `kr.investing.com` 403). 폴백 덕에
  **클러스터가 title-only로 전락한 사례는 사실상 0**(로그에 "본문 미확보" 없음).
- 판정: 폴백 체인이 의도대로 동작. 해외(investing.com) 403은 구조적이므로, 해당 소스는 대표 선정에서 후순위로 두면 추가 개선 가능(선택).

### ② classify (호출 A) — ⚠️ 동작하나 품질 과제
86건 적재 분포:
- **scope**: 회사 53 · 시장 전체 17 · 업종·테마 16. **frame**: PLAN 34 · OPINION 13 · INCIDENT 10 · PRICE 10 · TREND 8 · POLICY 7 · EARNINGS 4.
- **origin**: 국내 62 · 해외 24. **direction**: 상승 57 · 중립 14 · 하락 15.
- 7개 frame 모두 사용되고 분포 자체는 합리적(스키마·Literal 강제로 무효값 0).

세 가지 품질 과제(상세 [01](./01-frame-coverage-verification.md)):
1. **confidence 과신** — 86건 중 **72건이 정확히 0.9**, `needs_review`는 **2건뿐**. 억지 분류(비투자성 PR)도 0.9라
   confidence로는 미스핏을 못 거른다 → 검수 큐 신호로 부적합.
2. **OPINION 과소검출** — 전문가 칼럼·리포트가 PLAN/TREND/POLICY로 적재(독립 판정은 OPINION). 7개 안 최다 경계 오류.
3. **PLAN 과부하** — 최다(34)이며 비투자성 PR 5건을 흡수. 상류 relevance 필터 권장.

판정: 파이프라인은 정상 수행하나 **분류 프롬프트 보강**(OPINION 우선 규칙·거시 가이드)과 **검수 신호 재설계**(confidence 외 지표)가 필요.

### ③ enrich (OPINION 현재가 보강) — ⚠️ 동작·관측성 부족
OPINION frame일 때만 현재가를 조회해 괴리율 계산에 쓴다([enricher.py](../../services/analyzer/enricher.py), [10 §8](../design/10-content-pipeline-implementation.md)). 그 외 frame은 no-op.
- 대상은 OPINION **13건**. 노드는 정상 실행되나, **현재가 조회 적중/honest-blank 여부가 DB에 저장되지 않아** 적중률을 사후 집계할 수 없다.
- 판정: 기능은 동작하나 **관측성 부족**. 적중/blank 플래그를 `news_analysis`나 로그에 남기면 다음 평가에서 계측 가능(개선 포인트).

### ④ generate (호출 B) — ✅ 양호
frame별 4-head 명세를 주입하고 LLM은 answers만 생성, 코드가 label·question과 결합([content_generator.py](../../services/analyzer/content_generator.py)).
- **content_heads 길이: 86건 전부 정확히 4** (100% 완성). `hook_lines` **빈값 0건**.
- 확대 배치에서 **생성 실패 1/54**(cluster 300, `NoneType.answers` — LLM이 구조화 출력을 반환 못 한 일시 오류). 실패는 트랜잭션 격리로 다른 건에 무영향.
- OPINION 1단 종목 가드/재생성·금지어 후처리는 동작(가드 최종 실패는 `needs_review`로 흡수). 재생성 횟수는 미저장.
- 판정: 출력 구조 신뢰성 높음. 드문 `None` 반환에 대비해 **생성 단계 1회 재시도**를 더하면 견고성↑(개선 포인트).

### ⑤ 엔티티·섹터 백필 — ✅ 양호
분류 태그(이름)를 마스터 id로 해소해 `company_ids`·`sector_ids`에 적재([11 §3](../design/11-analysis-run-and-backfill.md)).
- **섹터**: sector_tag 107개 → `sectors.id` **107개 해소 = 100%**. 등장한 태그가 전부 GICS 대분류 11개 안(금융 36·IT 23·산업재 16·헬스케어 11…)
  → **"섹터=GICS, LLM 직접 분류" 결정([11 §4](../design/11-analysis-run-and-backfill.md))이 실제로 정합함을 검증**. 미해소 0건.
- **기업**: 언급 기업명 239개 → `company_entities.id` **124개 해소 = 52%**. 클러스터 기준 완전·초과 해소 23 · 부분 26 · 0개 해소 22.
  미해소는 **해외 기업(엔비디아·스페이스X)·미상장·마스터 미수록**이라 설계상 정상(원문은 `company_tags`에 보존).
- 판정: 의도대로 동작. 단 기업 해소율 52%는 "왜 빠졌나"가 안 보이므로, 미해소 사유(해외/미상장)를 구분해 남기면 활용도↑(선택).

### ⑥ persist — ✅ 양호
클러스터당 `news_analysis`(분류+백필)·`issue_docent`(콘텐츠) 각 1행, `ON CONFLICT DO NOTHING`으로 멱등.
- **행수 정합**: `news_analysis` 86 = `issue_docent` 86 = 분석 완료 클러스터 수. 분류만 있고 콘텐츠 없는 불일치 0.
- 멱등: 동일 클러스터 재실행 시 스킵(`--rerun`만 덮어씀) — 러너 로그에서 확인.
- 판정: 트랜잭션 경계(클러스터=1 커밋)·멱등·격리 모두 의도대로 수행.

## 4. 종합·개선 우선순위

골격은 신뢰성 있게 동작한다(①④⑤⑥ ✅). 개선은 품질·관측성에 집중:

1. **✅ 구현(→[04](./04-classification-improvement-history.md)) relevance 필터** — 비투자성 잡뉴스(PR·CSR·교육·부고)를 분류기
   `is_investment_relevant` 게이트로 판정해 콘텐츠 생성·적재 skip → ②의 PLAN 과부하·노이즈 해소.
2. **✅ 구현(→[04](./04-classification-improvement-history.md)) OPINION 분류 가이드 강화** — "주체가 전문가 의견이면 소재 불문 OPINION" 규칙 + 거시 가이드.
3. **(P2·미반영) 검수 신호 재설계** — confidence 과신으로 `needs_review`가 무력 → 별도 미스핏 신호 도입.
4. **(P2·미반영) enrich 적중률 계측** — OPINION 현재가 hit/blank 플래그 적재.
5. **(P3·미반영) generate 1회 재시도** — `None` 구조화 출력 대비.
6. **(P3·미반영) 기업 미해소 사유 구분** — 해외/미상장/미수록 라벨.

## 5. 참고 자료

- 설계: [10-content-pipeline-implementation.md](../design/10-content-pipeline-implementation.md) · [11-analysis-run-and-backfill.md](../design/11-analysis-run-and-backfill.md)
- 연계 평가: [01-frame-coverage-verification.md](./01-frame-coverage-verification.md)(classify 품질) · [02-summary-first-comparison.md](./02-summary-first-comparison.md)(입력 방식 실험)
- 코드: [services/pipeline/news_analyzer.py](../../services/pipeline/news_analyzer.py) · [scripts/run_analysis.py](../../scripts/run_analysis.py) · [app/db/queries.py](../../app/db/queries.py)
- 증거 로그: `/tmp/run_analysis_expand.log` (확대 배치 실행 기록)
