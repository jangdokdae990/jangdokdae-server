# 10. 콘텐츠 파이프라인 구현 설계 (분류 → 생성)

> **작성자** Kim minkyoung · **작성일** 2026-06-16
>
> **범위** 클러스터(top_issues) 인계 → scope×frame 분류 → 4-head 콘텐츠 생성 → Issue Docent 영속화까지의 **구현** 설계. 분류 개념은 [08](./08-pain-to-content-pipeline.md), 실증 검증은 [09](./09-classification-validation.md)를 따른다.
>
> **핵심 결정**: 분류 축 = scope(3) × frame(7, OPINION 포함) + origin·direction flag · 2-call 아키텍처(classify → generate, 각각 `with_structured_output`) · 프롬프트는 `prompts/*.yaml` · MVP는 **기사 본문 기반 스켈레톤**(08 §5 외부 데이터 보강은 후속 PR) · Airflow `analyze` Task가 LangGraph 단일 에이전트를 호출.

---

## 목차

- [1. 목적과 위치](#1-목적과-위치) · [2. 분류 체계](#2-분류-체계) · [3. 2-call 아키텍처](#3-2-call-아키텍처)
- [4. 프롬프트 (YAML)](#4-프롬프트-yaml) · [5. 스키마](#5-스키마) · [6. 모듈 구조](#6-모듈-구조)
- [7. 데이터 모델](#7-데이터-모델) · [8. LangGraph 플로우](#8-langgraph-플로우) · [9. 오케스트레이션](#9-오케스트레이션)
- [10. 스켈레톤 범위와 후속](#10-스켈레톤-범위와-후속) · [11. 참고 자료](#11-참고-자료)

---

## 1. 목적과 위치

```
수집 → 전처리 → 임베딩·클러스터링 → [분류 → 콘텐츠 생성 → Issue Docent]  ← 이 문서
```

`EmbeddingClusterer`가 적재한 `news_cluster`(importance 내림차순, → [05 §6.2](./05-embedding-clustering-design.md))를
받아 이슈별로 분류·생성해 `news_analysis`·`issue_docent`에 적재한다. 파이프라인에서 LLM이 흐름을 판단하는 유일한 단계다.

## 2. 분류 체계

08번을 그대로 구현한다. 두 축은 **서로 독립**이라 충돌 조합이 없다(어떤 scope × 어떤 frame도 정상).

**scope (주인공, 3)**: `회사` · `업종·테마` · `시장 전체`

**frame (읽는 법, 7)** — 내부 코드(영어, 불변)와 사용자 노출 이름(한글):

| code | 사용자 노출 | 무슨 뉴스 | head3 ★오해 방지 |
|------|------------|-----------|------------------|
| `EARNINGS` | 실적이 나왔어요 | 매출·이익 성적표 | 이게 계속될까요 |
| `INCIDENT` | 악재가 생겼어요 | 사고·소송·리콜·제재 | 일시적인가요, 계속될 문제인가요 |
| `PLAN` | 새 계획을 발표했어요 | 신제품·투자·수주·인수·주주환원 | 진짜 돈이 되려면 |
| `POLICY` | 제도가 바뀌어요 | 정책·규제·금리·세금 | 확정인가요, 검토 중인가요 |
| `TREND` | 업황이 달라져요 | 산업 흐름·수급 변화 | 잠깐인가요, 계속될 변화인가요 |
| `OPINION` | 전문가가 평가했어요 | 증권사 리포트·목표주가·의견 | 이 숫자, 믿어도 될까요 |
| `PRICE` | 주가만 움직였어요 | 이유 불명 급등락 | 진짜 이유일까요, 끼워 맞춘 걸까요 |

> **OPINION은 09번이 P0로 지적한 신규 frame**이다(08 §3-⑥). PLAN/TREND head를 빌려 쓰면 리포트가 산업분석으로
> 변질되므로, 전용 4-head로 **시선을 리포트 자체에 묶는다**:
> `[1단 누가, 뭐라고 했어요(종목·목표가·의견·직전대비 강제) / 2단 지금 주가에서 얼마나 더 본 거예요(현재가→목표가 괴리율) / ★3단 이 숫자, 믿어도 될까요(목표가를 떠받치는 가정 가시화) / 4단 앞으로 뭘 보면 될까요(가정 검증 지표)]`.
> 2단 괴리율은 **현재가 key 조회**가 필요해 §5 보강 중 **OPINION 현재가만 이번에 구현**한다(아래 §6·§10).

> **(2026-06-17 업데이트, →[11](./11-analysis-run-and-backfill.md))** `sector_tags`는 이후 **GICS 대분류 11개**
> (`sectors.name_ko`와 동일)로 직접 분류하도록 변경됐다(이전 15개 큐레이션 테마 폐쇄목록 대체). 이로써 분류 결과가
> `news_analysis.sector_ids`(→`sectors.id`)로 백필된다. 상세는 11번 §3·§4.
>
> **(2026-06-18 업데이트, →[04](../evaluation/04-classification-improvement-history.md))** 분류 프롬프트에
> **OPINION 우선 규칙**(전문가 의견이면 소재 불문 OPINION)·**거시지표 가이드**(물가·환율은 TREND/POLICY 우선)와
> **투자 관련성 게이트**(`is_investment_relevant`)를 추가했다. 비투자성(홍보·사회공헌·부고 등)이면 콘텐츠 생성을 건너뛴다(§8).

**origin** (`국내`/`해외`)·**direction** (`상승`/`하락`/`중립`)은 분류 축이 아니라 **생성 시 문구·첫 줄(hook)만 바꾸는 flag**다.
해외면 head1/2 라벨이 "해외에서 무슨 일이에요 / 우리 시장엔 어떻게 올까요"로 교체된다.

**원인 우선 규칙**: 주가 움직임은 결과다. 원인 사건(실적·사건·정책 등)을 먼저 찾아 frame을 정하고, 뚜렷한 원인이 없을 때만 `PRICE`.

## 3. 2-call 아키텍처

```
이슈(대표 기사 본문 + 서브 헤드라인)
  → [호출 A] NewsClassifier.classify  → ClassificationResult (scope·frame·origin·direction·confidence·tags)
  → [호출 B] ContentGenerator.generate → ContentResult (4-head·hook·연결모듈·근거/용어 span)
  → [호출 C] QuizGenerator.generate    → QuizOutput (term/issue/domain 3문항)
```

- 호출 A: `temperature=0` (결정적). 신뢰도 `< threshold`면 `needs_review=True`로 표시(검수 큐).
- 호출 B: `temperature=0.3`. frame별 head 명세를 user 프롬프트에 주입 → LLM은 answers 4개만 출력 → 코드가 label/question과 결합.
- 세 호출 모두 `ChatVertexAI(...).with_structured_output(Pydantic)`으로 JSON 파싱 오류를 제거한다.
- 퀴즈는 v1 구조를 유지하되 `term → issue → domain` 3문항 고정으로 확장한다.

## 4. 프롬프트 (YAML)

CLAUDE.md 원칙(프롬프트는 코드가 아닌 `prompts/*.yaml`)에 따라 3개 파일:

| 파일 | 내용 |
|------|------|
| `prompts/news_classify.yaml` | 호출 A 시스템 프롬프트(scope·frame 7·origin·direction·태그 규칙·원인 우선 규칙) + user 템플릿 + few-shot |
| `prompts/news_generate.yaml` | 호출 B 시스템 프롬프트(단정/추론 구분·인과 강제·금지 표현·톤 3원칙·hook 규칙) + user 조립 정적 텍스트 |
| `prompts/frame_head_specs.yaml` | frame별 메타데이터(`user_label`·`classify_hint`·`connection_hint`)와 4-head 명세(`label`·`question`·`guidance?`·`misconception?`·`global_label?`) |

## 5. 스키마

`services/analyzer/schemas.py` (Pydantic, `with_structured_output` 대상):

- `ClassificationResult` — `scope_reasoning`·`scope`·`frame_reasoning`·`frame`(7 Literal)·`origin`·`direction`·`confidence`·`is_investment_relevant`(투자 관련성 게이트, →[04](../evaluation/04-classification-improvement-history.md))·`evidence`·`alternatives[]`·`sector_tags[]`·`company_tags[{name,role}]`·`term_tags[]`
- `ContentDraft` (LLM 직출력) — `answers[4]`·`hook_lines{pain,neutral}`·`evidence_spans[]`·`term_spans[]`·`connection_module[]`
- `ContentResult`/`Head` — `label`·`question`(코드 주입) + `answer`(LLM) 결합 최종형
- `QuizOutput` — `quizzes[3]`, 고정 순서 `quiz-1(term)`·`quiz-2(issue)`·`quiz-3(domain)`, `answer_index`는 0-based
- `Article`·`Issue` — 내부 데이터 구조(대표 기사 + 서브)

## 6. 모듈 구조

서비스 폴더명은 행위자 명사(-er/-or) 규칙 준수.

```
app/llm/
  prompt_loader.py   load_prompt(name) → prompts/<name>.yaml dict
  chains.py          make_classifier() / make_generator() / make_quiz_generator() — ChatVertexAI + with_structured_output
  graph.py, state.py LangGraph 단일 에이전트(§8)
services/analyzer/
  schemas.py         Pydantic 스키마(§5)
  frames.py          taxonomy 상수(FRAMES·SECTOR_TAGS·FORBIDDEN_WORDS) + head-spec 로딩
  classifier.py      NewsClassifier (호출 A)
  content_generator.py ContentGenerator (호출 B + 금지어 후처리 + OPINION 1단 가드/재생성 + 용어 중복제거)
  quiz_generator.py  QuizGenerator (호출 C, term/issue/domain 3문항 고정)
  enricher.py        DataEnricher — OPINION 현재가 key 조회 구현(그 외 frame은 no-op, §5 후속)
  article_fetcher.py (기존) 대표 기사 본문 fetch
services/pipeline/
  news_analyzer.py   NewsAnalyzer.run(db) → NewsAnalyzerState — 오케스트레이터
```

분류 결과의 `company_tags`는 기업명만 갖는다. OPINION 현재가 보강은 `app/db/queries.py`의
`get_company_by_name`(명→`company_entities`)·`get_latest_stock_price`(코드→`stock_prices` 최신 종가)로
괴리율 계산용 현재가를 가져온다(미스 시 honest-blank).

## 7. 데이터 모델

이슈(클러스터) 단위. `is_analyzed` 플래그로 멱등 핸드오프(상류 컨벤션과 동일).

### 7.1 `news_analysis` (클러스터당 분류 — 호출 A 결과)

한 이슈(클러스터)의 **분류 결과**를 1행으로 적재한다. `cluster_id` 유니크라 재실행해도 중복되지 않는다(멱등).

| 컬럼 | 타입 | 의미 |
|------|------|------|
| `cluster_id` | int FK→`news_cluster.id` | 어느 이슈(클러스터)의 분류인가. 클러스터당 1행(유니크) |
| `scope` | str(20) | **주인공** — `회사` / `업종·테마` / `시장 전체` 중 1 |
| `frame` | str(20) | **읽는 법**(내부 코드) — `EARNINGS`/`INCIDENT`/`PLAN`/`POLICY`/`TREND`/`OPINION`/`PRICE` 중 1 |
| `origin` | str(10) | **발생지** — `국내` / `해외`. 생성 시 head 라벨·문구를 바꾸는 flag |
| `direction` | str(10) | **호악재 방향** — `상승` / `하락` / `중립`. 첫 줄(hook) 프레이밍용 flag |
| `confidence` | float | 분류 신뢰도 `0.0~1.0`. threshold 미만이면 `needs_review=true` |
| `sector_tags` | text[] | LLM이 고른 **섹터명 원문**(GICS 대분류 11개, →§2·11번 §4) |
| `company_tags` | jsonb | **언급 기업 원문** `[{name, role}]` — role=`primary`(직접 영향) / `mentioned`(비교·예시) |
| `company_ids` | int[] (GIN) | `company_tags` 이름을 `company_entities.id`로 해소한 **백필**. 미매칭 제외, 원문은 `company_tags`에 보존 |
| `sector_ids` | int[] (GIN) | `sector_tags`를 `sectors.id`(GICS)로 해소한 **백필**. 미매칭 제외 |
| `term_tags` | text[] | 설명이 필요한 금융·시장 **용어** 목록 |
| `needs_review` | bool | 저신뢰 **또는** OPINION 1단 종목 가드 최종 실패 → 검수 큐 대상 |
| `is_investment_relevant` | bool | 투자 관련성 게이트. false면 비투자성(홍보·사회공헌·부고 등) → 콘텐츠 생성·`issue_docent` 적재 skip(→[04](../evaluation/04-classification-improvement-history.md)). 기본 true |
| `analyzed_at` | timestamp(KST) | 분류 적재 시각 |

> **백필 `company_ids`·`sector_ids`(2026-06-17 추가, →[11](./11-analysis-run-and-backfill.md) §3)**: 태그(이름)만으로는
> "특정 기업/섹터를 언급한 이슈" 조회·주가 연동이 안 돼, 마스터 테이블 id로 해소한 두 배열 컬럼을 더했다(GIN 인덱스).
> 해소는 `app/db/queries.py`의 `resolve_company_ids`·`resolve_sector_ids`, 적재는 `NewsAnalyzer._persist`.
> 조회: `WHERE :id = ANY(company_ids)` / `... = ANY(sector_ids)`, `company_id → stock_code → stock_prices`로 주가 연동.

### 7.2 `issue_docent` (클러스터당 콘텐츠 — 호출 B 결과)

한 이슈의 **생성 콘텐츠**를 1행으로 적재한다. 분류(`news_analysis`)와 grain은 같지만 책임이 달라 테이블을 나눈다.

| 컬럼 | 타입 | 의미 |
|------|------|------|
| `cluster_id` | int FK→`news_cluster.id` | 어느 이슈의 콘텐츠인가. 클러스터당 1행(유니크) |
| `title` | str(500) | 이슈 제목(대표기사 제목) |
| `hook_lines` | jsonb | 첫 줄 후킹 2종 `{pain, neutral}` — 고통 공감형 / 중립 요약형 |
| `content_heads` | jsonb | **4-head 본문** `[{label, question, answer}]×4`. label·question은 frame 명세에서 코드가 주입, answer만 LLM 생성 |
| `connection_module` | jsonb | 타 섹터/종목 연결·오해 차단 `[{sector, sentiment, reason, company_candidates}]` |
| `evidence_spans` | jsonb | 단정형 핵심 사실 + 근거 문장 `[{head, claim, sentence}]` — 본문 주장의 출처 매핑 |
| `term_spans` | jsonb | 용어 풀이 `[{term, sentence}]` — 용어와 사용 문장(클릭형, 중복 제거됨) |
| `quizzes` | jsonb | 퀴즈 `[{quiz_id, kind, question, options, answer_index, explanation}]×3` — `term`/`issue`/`domain` 고정 |
| `is_published` | bool | 발행 여부. 검수 통과 전 `false` |
| `created_at` | timestamp(KST) | 콘텐츠 생성 시각 |

> `source_refs`(08 §8 출처 배지)는 §5 데이터 보강과 함께 후속 PR에서 추가한다.

마이그레이션: `alembic revision --autogenerate` → `alembic upgrade head`.

## 8. LangGraph 플로우

06 §18.2 MVP(단일 에이전트)를 스켈레톤 범위로 구현한다. fetch·persist는 DB 경계라 오케스트레이터가 맡고,
그래프는 LLM·보강 단계만 담는다.

```
(fetch) → classify ─┬─ relevant ─→ enrich → generate → (persist 분류+콘텐츠)
                    │                  │           │
                    │                  │           └ OPINION 1단 종목 가드 실패 시 1회 재생성, 그래도 실패면 needs_review
                    │                  └ OPINION이면 현재가 조회(괴리율용), 그 외 no-op
                    └─ 비투자성 ──────────────────→ END (분류만 persist, issue_docent skip)
```

> **(2026-06-18, →[04](../evaluation/04-classification-improvement-history.md))** classify 직후 **조건부 분기**가 추가됐다.
> `is_investment_relevant=false`(비투자성)면 enrich·generate를 건너뛰고(생성 LLM 호출 절감) 분류만 적재한다(relevance 필터).

신규 콘텐츠 생성 흐름은 `classify → enrich → generate → quiz → persist`다. quiz 실패는 콘텐츠 저장을 막는다.
기존 `issue_docent` 행은 `scripts/backfill_quizzes.py`로 quiz만 백필한다.

State(`AnalysisState`): `issue` · `db` · `classification` · `enrichment` · `content` · `quizzes` · `generation_review`.
노드는 async — classify·generate는 동기 LLM 호출을 `asyncio.to_thread`로 오프로드, enrich는 DB 조회.
연결 모듈은 generate 산출 `connection_module`로 흡수, 검수 큐 API·multi-agent 승급(06 §18.3)은 후속.

## 9. 오케스트레이션

`services/pipeline/news_analyzer.py::NewsAnalyzer.run(db)`가 top 클러스터를 fetch해 이슈별로 graph를 돌리고,
이슈 간 `llm_request_delay_seconds`로 rate-limit, 부분 실패는 `State.errors`로 격리(상류 `NewsCollector`·`EmbeddingClusterer` 패턴).
Airflow DAG(`dags/jangdokdae_pipeline.py`)에 `analyze` `ExternalPythonOperator` 추가, `embed_cluster >> analyze`.

> **(2026-06-17 업데이트, →[11](./11-analysis-run-and-backfill.md))** 한 클러스터 처리(happy-path)는
> `NewsAnalyzer.analyze_cluster(db, cluster)`로 추출돼 `run()`과 분석 전용 러너(`scripts/run_analysis.py`)가 함께
> 쓴다. 러너는 날짜 무관·특정 id·`--min-size`·`--rerun`으로 분석 단계만 단독 실행한다(로컬 검증용). 상세는 11번 §5.

## 10. 스켈레톤 범위와 후속

| 구현 (이번) | 후속 PR |
|-------------|---------|
| scope×frame 분류(7, OPINION 포함) | 08 §5 나머지 보강 — 공시·사업보고서 RAG + 재무·거시 key 조회 |
| 기사 본문 기반 4-head 생성 + hook + 연결 모듈 | `source_refs` 출처 배지(P4) |
| **OPINION 현재가 보강(괴리율)** — `company_entities`→`stock_prices` key 조회, 미스 시 honest-blank | 실적 head 분기(컨센서스형/통계형) |
| **OPINION 1단 종목 가드 + 1회 재생성**, 용어 span 중복 제거, 금지어 후처리·신뢰도 검수 큐 플래그 | 검수 큐 운영 API |
| **퀴즈 생성** — v1 구조 유지, `term`/`issue`/`domain` 3문항 고정, 기존 행은 quiz-only 백필 | 퀴즈 결과 저장/학습 기록 |
| 단일 LangGraph 에이전트 | 품질 미달 시 supervisor-worker 승급(06 §18.3) |

> 09번 Q3 결론대로 "골격"은 완성됐고, 차별점인 "데이터 보강(살)"은 **OPINION 현재가부터** 채우기 시작한다(09 P0).

## 11. 참고 자료

- [`08-pain-to-content-pipeline.md`](./08-pain-to-content-pipeline.md) — 분류·콘텐츠 개념 설계(scope×frame·4-head·§5 자료 매핑)
- [`09-classification-validation.md`](./09-classification-validation.md) — 실증 검증·개선 과제(OPINION 전용 head = P0)
- [`06-news-analysis-design.md`](./06-news-analysis-design.md) — 콘텐츠 구조·톤·LangGraph 에이전트 설계(계승)
- [`05-embedding-clustering-design.md`](./05-embedding-clustering-design.md) — 상류(클러스터·top_issues 인계)
- [`11-analysis-run-and-backfill.md`](./11-analysis-run-and-backfill.md) — as-built 변경(엔티티/섹터 백필·GICS·분석 러너·실행 환경)
- [`evaluation/04-classification-improvement-history.md`](../evaluation/04-classification-improvement-history.md) — 분류 개선(OPINION 우선·거시·relevance 필터) 반영 전후 히스토리
