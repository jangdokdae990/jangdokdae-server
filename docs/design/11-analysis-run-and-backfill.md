# 11. 분석 단계 실행·엔티티/섹터 백필 (as-built)

> **작성자** Lee subeom (as-built 기록) · **작성일** 2026-06-17
>
> **범위** [10](./10-content-pipeline-implementation.md)의 분류→생성→영속화 설계 **이후 실제로 구현·실행한 변경**을 기록한다.
> ① 클러스터→콘텐츠→DB 저장 end-to-end 실행 경로, ② 언급 기업·섹터를 마스터로 해소하는 **백필**(`company_ids`·`sector_ids`),
> ③ 섹터를 **GICS 대분류**로 분류하도록 변경, ④ 분석 단계만 단독 실행하는 **러너**(`scripts/run_analysis.py`),
> ⑤ 실행 환경(인증)과 알려진 한계. 분류 체계 적합성 검증은 [evaluation/01](../evaluation/01-frame-coverage-verification.md).

---

## 목차
1. [목적과 위치](#1-목적과-위치)
2. [전체 흐름 (cluster → content → DB)](#2-전체-흐름-cluster--content--db)
3. [엔티티·섹터 백필](#3-엔티티섹터-백필)
4. [섹터 = GICS 결정](#4-섹터--gics-결정)
5. [분석 전용 러너](#5-분석-전용-러너)
6. [실행 환경·인증](#6-실행-환경인증)
7. [알려진 한계](#7-알려진-한계)
8. [참고 자료](#8-참고-자료)

---

## 1. 목적과 위치

[10번](./10-content-pipeline-implementation.md)은 분류→생성→영속화의 **설계**다. 본 문서는 그 위에 실제로
얹은 **as-built 변경 + 실행 런북**이다. 핵심 추가는 "생성된 콘텐츠를 DB에 적재할 때, 언급된 기업과 섹터를
**마스터 테이블과 연결**(백필)한다"이며, 이를 검증하려고 분석 단계를 단독 실행하는 러너를 만들었다.

```
EmbeddingClusterer → news_cluster ──▶ [분석 단계] ──▶ news_analysis · issue_docent
                                         │
                  fetch 본문 → classify → enrich → generate → 백필 해소 → 적재
```

## 2. 전체 흐름 (cluster → content → DB)

한 클러스터를 처리하는 단위는 [`NewsAnalyzer.analyze_cluster(db, cluster)`](../../services/pipeline/news_analyzer.py)로
추출돼 있다(운영 `run()`과 분석 러너가 함께 재사용). 순서:

1. **본문 fetch** — `_build_issue(db, cluster)`가 `get_cluster_articles`로 멤버 기사를 중심근접순으로 가져오고,
   `fetch_first_available`로 대표부터 본문을 시도(페이월·실패 시 다음 후보, 전부 실패면 title-only). →
   `Issue(main_article{title,body,url}, sub_articles[title])`.
2. **classify → enrich → generate** — LangGraph 단일 에이전트(`app/llm/graph.py`). classify·generate는
   `with_structured_output`, enrich는 OPINION 현재가 조회. (설계 [10 §8](./10-content-pipeline-implementation.md))
3. **백필 해소 + 적재** — `_persist`에서 분류의 `company_tags`·`sector_tags`를 마스터 id로 해소(§3)한 뒤
   `save_news_analysis`(분류+백필)·`save_issue_docent`(콘텐츠)·`mark_news_analyzed` 호출.
4. **commit** — 한 클러스터 = 한 트랜잭션. 실패는 호출부에서 격리(아래 §5).

## 3. 엔티티·섹터 백필

생성 콘텐츠 적재 시, 자유 텍스트 태그만으로는 "특정 기업/섹터를 언급한 이슈" 조회·주가 연동이 불가능했다.
그래서 **태그(이름)를 마스터 id로 해소한 백필 컬럼**을 [`news_analysis`](../../app/db/orm_models/news_analysis.py)에 추가했다.

| 컬럼 | 의미 | 해소 방법 |
|------|------|-----------|
| `company_ids` `int[]` | `company_tags`(언급 기업)의 **이름** → `company_entities.id` | `resolve_company_ids` — `name_ko` 정확 일치 **또는** `aliases` 배열 겹침(`&&`) |
| `sector_ids` `int[]` | `sector_tags`(GICS) → `sectors.id` | `resolve_sector_ids` — `sectors.name_ko` 정확 일치 |

- 두 해소 함수는 [`app/db/queries.py`](../../app/db/queries.py)에 있고 N개를 1쿼리로 묶어 처리. **미매칭은 배열에서
  제외**되고 원문 태그(`company_tags`·`sector_tags`)는 그대로 보존 → 마스터 미수록 기업/섹터에도 안전.
- **기업 = 뉴스에 언급된 기업**이라는 의도. 섹터(§4)와 독립이며, 비상장·기관(협회/예탁원 등 company_tags 제외 규칙)은
  애초에 빠진다. 예: "고영·삼성전자·SK하이닉스" 언급 중 상장 3사만 `company_ids`, 스페이스X·엔비디아(미상장/미수록)는 제외.
- 관계형 조회 가속을 위해 두 컬럼에 **GIN 인덱스**(`ix_news_analysis_company_ids`·`ix_news_analysis_sector_ids`).
  조회: `WHERE :id = ANY(company_ids)` / `... = ANY(sector_ids)`. `company_id → stock_code → stock_prices`로 주가 연동.
- 마이그레이션: `migrations/versions/d7e9a1c2b3f4_add_news_analysis_company_ids_sector_ids.py`(수기 작성 — .env/DB 없이 autogenerate 불가 환경).
- **구현 노트**: 모델의 `aliases`는 generic `sa.ARRAY`라 `.overlap()`이 없다 → `resolve_company_ids`에서
  `type_coerce(..., postgresql.ARRAY(Text))` 후 `.overlap()` 사용.

## 4. 섹터 = GICS 결정

이슈의 "섹터"는 **GICS 대분류 11개**(`에너지·소재·산업재·경기소비재·필수소비재·헬스케어·금융·IT·
커뮤니케이션서비스·유틸리티·부동산`)로 정의한다. = `sectors` 마스터(`name_ko`)와 동일 어휘.

- LLM(분류기)이 이 11개로 **직접** 분류하도록 [`prompts/news_classify.yaml`](../../prompts/news_classify.yaml)의
  `sector_tags` 폐쇄목록 + [`frames.py`](../../services/analyzer/frames.py) `SECTOR_TAGS`를 GICS로 교체(이전엔 15개 큐레이션 테마).
  업종→GICS 매핑 도움말과 예시도 프롬프트에 포함(반도체→IT, 통신→커뮤니케이션서비스, 2차전지→소재 등).
- 따라서 `sector_tags`가 곧 GICS 이름 → `resolve_sector_ids`가 `sectors.name_ko`로 그대로 매칭 → `sector_ids`가 채워진다.
- **트레이드오프**: GICS 대분류는 거칠다(반도체·소프트웨어 모두 IT, 2차전지·철강 모두 소재). 더 세분한
  `industries`(74) 단위가 필요하면 별도 `industries` ORM 모델 + `industry_ids` 컬럼이 필요하다(후속).

## 5. 분석 전용 러너

운영 진입점([`runner.py`](../../services/pipeline/runner.py))은 수집→임베딩→분석 전체를 돌린다. 분석 단계만,
그리고 **과거 날짜 클러스터까지** 대상으로 돌리려고 [`scripts/run_analysis.py`](../../scripts/run_analysis.py)를 추가했다.
(운영 `get_unanalyzed_clusters`는 `run_date == 오늘(KST)`만 본다.)

```bash
# 최신 미분석 1건 / N건 / 무제한(0)
uv run python -m scripts.run_analysis [--limit N]
# 크기 필터 (size >= n)
uv run python -m scripts.run_analysis --min-size 2 --limit 0
# 특정 클러스터 / 재분석(기존 결과 삭제 후)
uv run python -m scripts.run_analysis --cluster-id 120 [--rerun]
# 이미 분석된 전체를 재분석(분류 개선 운영 반영 등) — 배치 --rerun
uv run python -m scripts.run_analysis --min-size 1 --limit 0 --rerun
```

- 보조 쿼리([`queries.py`](../../app/db/queries.py)): `get_latest_unanalyzed_clusters(db, limit, min_size)`(날짜 무관,
  `limit<=0`=무제한), **`get_analyzed_clusters`(배치 `--rerun` 대상 = 이미 분석된 클러스터)**,
  `get_cluster_by_id`, `delete_analysis_for_cluster`(--rerun — save가 ON CONFLICT DO NOTHING이라 삭제 없이는 덮어쓰기 불가).
- **배치 `--rerun`**(--cluster-id 없이): `get_analyzed_clusters`로 이미 분석된 클러스터를 골라 delete→재분석.
  분류 개선([eval/04](../evaluation/04-classification-improvement-history.md))을 기존 적재분에 일괄 반영할 때 쓴다.
  주의: per-cluster는 delete를 먼저 commit하므로, 재분석이 일시 오류로 실패하면 그 건은 분석이 비는 상태가 된다
  → 실패분은 `--cluster-id`로 재실행해 복구한다(2026-06-19 운영 반영 시 8건 복구).
- **건별 독립 세션** — 클러스터마다 새 `AsyncSessionLocal()`로 처리해, 한 건 실패가 연결을 오염시켜 배치를 멈추지
  않게 격리. 끝에 완료/스킵/실패 요약.
- 콘솔에 title·scope/frame·`company_tags↔company_ids`·`sector_tags↔sector_ids`·heads 요약을 출력해 눈으로 검증.

## 6. 실행 환경·인증

분류·생성은 `ChatVertexAI`(Vertex AI)라 **ADC 인증 + GICS 프로젝트**가 필요하다(`GOOGLE_API_KEY`는 미사용).

- **프로젝트**: 팀 프로젝트(`kt-cloud-jangdokdae`)는 개인 계정에 Vertex 권한이 없고, **SA 키 생성은 조직 정책
  (`iam.disableServiceAccountKeyCreation`)으로 차단**된다(본인이 못 풂). → 로컬 테스트는 **사용자 소유 프로젝트**
  (`개인 Vertex 프로젝트`, Vertex API·결제 활성)로 돌린다.
- **설정**: `gcloud auth application-default set-quota-project <내-프로젝트>` 후 실행 시
  `GOOGLE_CLOUD_PROJECT=<내-프로젝트>`로 덮어쓴다.
- **키 파일 분기 회피**: `.env`의 `GOOGLE_APPLICATION_CREDENTIALS`가 없는 파일을 가리키면 [`config.py`](../../app/config.py)가
  그 경로를 os.environ에 넣어 ADC가 있어도 인증이 깨진다. 실행 시 `GOOGLE_APPLICATION_CREDENTIALS=`(빈 값)로
  덮어쓰면 키 분기를 건너뛰고 ADC로 폴백한다.

```bash
GOOGLE_CLOUD_PROJECT=<vertex-project> GOOGLE_APPLICATION_CREDENTIALS= \
  uv run python -m scripts.run_analysis --min-size 2 --limit 0
```
- 리전: `GOOGLE_CLOUD_LOCATION=asia-northeast3`에서 모델 미제공 에러 시 `us-central1`로 덮어써 재시도.

## 7. 알려진 한계

- **DB 스키마 분기**: 라이브 Neon은 GICS 계층(`sectors`→`industry_groups`→`industries`)으로 재시드돼 있고
  alembic 리비전이 `fa6e579bc7dc`(로컬에 없음)다. 반면 이 repo엔 `industry_groups`/`industries` 모델·마이그레이션이
  없다(설계상 seed/수동 관리 — [company_master_collector.py](../../services/collector/company_master_collector.py)
  주석 참조). `news_analysis`·`issue_docent`는 DB에 없어 ORM에서 **두 테이블만 create_all로 생성**했다.
  → 정식 동기화 시 alembic 계보 정합을 별도로 맞춰야 한다.
- **기업 GICS 미분류**: `company_entities.sector_id`가 전부 NULL(기업→GICS 매핑 미구현). 그래서 "이슈 섹터"는
  기업에서 유도하지 않고 LLM의 GICS 분류(§4)로 채운다.
- **오류 경로의 `MissingGreenlet`**: 한 클러스터 처리 중 예외 발생 시 rollback 경로에서 `pool_pre_ping`이 async와
  충돌해 원인 예외를 가릴 수 있다(정상 경로 무영향). 러너는 rollback 실패도 삼켜 배치를 계속한다.
- **분류 체계 적합성**: 7개 frame은 투자 뉴스엔 충분(85건 중 85% 적합도 만점)하나, 비투자성 잡뉴스(PR/사회공헌/ESG/교육/부고)는
  포착 못 해 PLAN·INCIDENT에 흡수된다(표본 확대 후 7%). 7개 안에서는 **OPINION 과소검출**이 최다 경계 오류.
  → 상류 relevance 필터 + OPINION 가이드 강화 권장. 근거는 [evaluation/01](../evaluation/01-frame-coverage-verification.md)(2026-06-18 2개 일자 85건으로 재실행).
- **단계별 수행 평가**: fetch→classify→enrich→generate→백필→persist 각 단계의 수행 품질은
  [evaluation/03](../evaluation/03-pipeline-stage-evaluation.md) 참조 — 골격·백필·persist는 양호, 과제는 분류 품질(confidence 과신·OPINION 과소검출)과 enrich 관측성.
- **섹터 백필 정합 검증**: 확대 표본에서 sector_tag 107개가 `sectors.id`로 **100% 해소**됨 → §4의 "섹터=GICS, LLM 직접 분류" 결정이 실제로 정합함을 확인([evaluation/03 §3-⑤](../evaluation/03-pipeline-stage-evaluation.md)).

## 8. 참고 자료

- [`10-content-pipeline-implementation.md`](./10-content-pipeline-implementation.md) — 분류→생성→영속화 설계(본 문서의 토대)
- [`01-frame-coverage-verification.md`](../evaluation/01-frame-coverage-verification.md) — 7개 frame 적합성 검증
- [`03-pipeline-stage-evaluation.md`](../evaluation/03-pipeline-stage-evaluation.md) — 분석 단계별 수행 평가(fetch~persist)
- [`04-classification-improvement-history.md`](../evaluation/04-classification-improvement-history.md) — 분류 개선(OPINION 우선·거시·relevance 필터) 반영 전후 히스토리

> **(2026-06-18 as-built, →[04](../evaluation/04-classification-improvement-history.md))** classify 단계에
> **relevance 필터**가 추가됐다 — 분류기가 `is_investment_relevant=false`(비투자성)로 판정하면 그래프 조건부
> 분기로 generate를 건너뛰고, `_persist`는 분류만 남기고 `issue_docent`를 생략한다(§2 흐름의 분기). 컬럼은
> `news_analysis.is_investment_relevant`(마이그레이션 `e8f1a2b3c4d5`, additive·기본 true). 프롬프트엔 OPINION 우선·거시 가이드도 함께 반영.
- 코드: [`services/pipeline/news_analyzer.py`](../../services/pipeline/news_analyzer.py)(`analyze_cluster`) ·
  [`app/db/queries.py`](../../app/db/queries.py)(`resolve_company_ids`·`resolve_sector_ids`·러너 조회) ·
  [`scripts/run_analysis.py`](../../scripts/run_analysis.py) · [`app/db/orm_models/news_analysis.py`](../../app/db/orm_models/news_analysis.py)
- 마이그레이션: `migrations/versions/d7e9a1c2b3f4_add_news_analysis_company_ids_sector_ids.py`
