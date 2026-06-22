# 13. Issue Docent 관심사 태깅 · LLM 제목 생성

> **작성자** Kim minkyoung · **작성일** 2026-06-22
>
> **범위** 발행 콘텐츠(`issue_docent`)에 **시장·섹터·종목** 태그를 추가해 온보딩 관심사 기반 피드 필터링을 가능하게 하고, 제목을 **LLM 생성**으로 전환한 변경. 콘텐츠 파이프라인 구현은 [10](./10-content-pipeline-implementation.md), 온보딩 관심사 모델은 `user_interest_*` 테이블을 따른다.
>
> **핵심 결정**: market = **종목 거래소**(`CompanyEntity.market` KOSPI/KOSDAQ) → `markets.code` 일치로 해소, 종목으로 못 잡는 해외 이슈는 `GLOBAL`(기타 해외 시장)로 폴백 · sector·company = 분류 단계에서 이미 해소되는 `sector_ids`/`company_ids` **재사용**(news_analysis와 동일 소스) · `issue_docent`에 **비정규화 저장**(피드 조회 시 조인 회피) · title = 호출 B 콘텐츠 생성 시 LLM이 함께 출력(누락 시 원문 제목 폴백) · alembic **분기 head 2개 병합**.

---

## 목차

- [1. 배경과 문제](#1-배경과-문제) · [2. 변경 개요](#2-변경-개요) · [3. 데이터 모델](#3-데이터-모델)
- [4. 추출·저장 흐름](#4-추출저장-흐름) · [5. LLM 제목 생성](#5-llm-제목-생성) · [6. 마이그레이션 head 병합](#6-마이그레이션-head-병합)
- [7. 변경 파일](#7-변경-파일) · [8. 검증](#8-검증) · [9. 후속 과제](#9-후속-과제) · [10. 참고 자료](#10-참고-자료)

---

## 1. 배경과 문제

콘텐츠 파이프라인([10](./10-content-pipeline-implementation.md))이 클러스터당 1행으로 `issue_docent`(발행용 콘텐츠)를 적재한다. 한편 온보딩에서 사용자는 **시장·섹터·종목** 관심사를 `user_interest_market` / `user_interest_sector` / `user_interest_company`에 등록한다.

문제는 둘이 연결되지 않았다는 점이다.

- `issue_docent`에는 market/sector/company가 없어 **"이 사용자의 관심사에 맞는 이슈"를 조회할 수 없었다.** 분류 결과인 `news_analysis`에는 `company_ids`/`sector_ids`가 있었지만 발행 콘텐츠 테이블에는 없었다.
- `title`이 **대표 기사 원문 헤드라인을 그대로 복사**(`issue.main_article.title`)해, 주린이용 톤·길이와 맞지 않고 언론사 표현이 그대로 노출됐다.

## 2. 변경 개요

| 항목 | 변경 전 | 변경 후 |
|------|---------|---------|
| 관심사 태그 | 없음 | `issue_docent.market_ids` / `sector_ids` / `company_ids` 적재 |
| market 출처 | — | **종목 거래소**(`CompanyEntity.market`) → `markets.id`, 해외는 `GLOBAL` 폴백 |
| sector·company 출처 | (news_analysis에만) | 분류 단계 해소값 **재사용**, issue_docent에도 저장 |
| title | 원문 기사 제목 복사 | LLM이 호출 B에서 생성(누락 시 원문 폴백) |

설계 결정 두 가지:

- **비정규화**: sector/company id는 `news_analysis`에도 있지만, 피드는 `issue_docent`를 직접 조회하므로 조인을 피하기 위해 같은 값을 `issue_docent`에도 저장한다. `news_analysis`의 컬럼·인덱스 패턴을 그대로 미러링한다.
- **market은 종목 거래소 기반**: 실제 `markets` 마스터는 거래소·지수 단위(`KOSPI`·`KOSDAQ`·`NASDAQ`·`SP500`·`US_ETF`·`GLOBAL`)다. 종목은 자신의 거래소를 `CompanyEntity.market`(KOSPI/KOSDAQ)으로 알고 있으므로, 이슈에 연관된 종목의 거래소를 `markets.code`와 일치시켜 시장을 해소한다. 종목 유니버스가 국내뿐이라 종목 기반은 KOSPI/KOSDAQ로 수렴하고, **종목으로 못 잡는 해외 이슈는 `GLOBAL`(기타 해외 시장)로 폴백**한다. 국내인데 종목이 없는 이슈(scope=`시장 전체`)는 빈 값으로 둔다(불확실한 시장을 억지로 붙이지 않음).

## 3. 데이터 모델

`issue_docent`에 배열 컬럼 3개와 GIN 인덱스 3개를 추가한다. 타입·기본값·인덱스 방식은 `news_analysis.company_ids`/`sector_ids`와 동일하다.

| 컬럼 | 타입 | 해소 소스 |
|------|------|-----------|
| `market_ids` | `integer[]` | 종목 거래소(`CompanyEntity.market`) → `markets.id` (해외는 `GLOBAL` 폴백) |
| `sector_ids` | `integer[]` | `sector_tags` → `sectors.id` |
| `company_ids` | `integer[]` | `company_tags` → `company_entities.id` |

- 기본값 `'{}'::integer[]`, `NOT NULL` — 기존 행·미매칭에도 안전.
- 인덱스 `ix_issue_docent_{market,sector,company}_ids` (`postgresql_using='gin'`) — 관심사 `:id = ANY(...)` 조회 가속.
- 원문 태그(`company_tags`·`sector_tags`)는 `news_analysis`에 그대로 보존되므로, 마스터 미수록 기업·섹터도 손실 없다(미매칭 id만 빠짐).

## 4. 추출·저장 흐름

기존 `NewsAnalyzer._persist`가 이미 분류 태그를 마스터 id로 해소하고 있었다. 여기에 market 해소만 더해 `issue_docent`까지 흘려보낸다.

```
classify (origin·sector_tags·company_tags)
  → resolve_company_ids / resolve_sector_ids       # 기존 재사용
  → resolve_market_ids(company_ids, origin)         # 신규: 종목 거래소 → market, 해외는 GLOBAL
  → save_issue_docent(market_ids, sector_ids, company_ids, title, ...)
```

- `resolve_market_ids(db, company_ids, origin)` — 해소된 종목의 거래소(`CompanyEntity.market`)를 `markets.code`와 조인해 `markets.id`로 해소한다(중복 제거). 종목으로 못 잡고 `origin`이 `해외`면 `GLOBAL`로 폴백, 국내인데 종목이 없으면 빈 리스트. company id 기반이 sector/company 해소 뒤에 와야 하므로 호출 순서를 조정했다.
- `save_issue_docent`에 `market_ids`/`sector_ids`/`company_ids` 키워드를 추가하고 `on_conflict_do_nothing`(클러스터당 1행, 멱등)은 유지한다.

## 5. LLM 제목 생성

제목을 **호출 B(콘텐츠 생성)** 출력에 포함시킨다. 별도 LLM 호출을 늘리지 않는다.

- 스키마: `ContentDraft`(LLM 직접 출력)에 `title` 필드 추가, `ContentResult`에도 `title`(기본 `""`).
- 프롬프트 `prompts/news_generate.yaml`: 출력 규칙·JSON 예시·`user_template` 출력 지시에 `title`을 추가. **원문 헤드라인 복사 금지**, 30자 내외, 본문과 동일한 금지 표현·방향 예측 금지 규칙 적용.
- `ContentGenerator.generate()`가 `ContentResult(title=draft.title, ...)`로 전달.
- `_persist`는 `title = content.title or issue.main_article.title` — LLM이 빈 제목을 주면 원문 제목으로 **폴백**해 `NOT NULL` 컬럼을 안전하게 채운다.

## 6. 마이그레이션

신규 리비전 `f3a7c9d2e1b8`는 main의 단일 head(`e89f78e7e898`) 위에 issue_docent 컬럼·인덱스만 추가한다(수기 작성). 분기됐던 alembic head는 main 측 `e89f78e7e898`(collector·content-pipeline 병합)에서 이미 단일화돼 있어, 본 리비전은 그 위에 선형으로 얹힌다.

> 이 프로젝트의 마이그레이션은 수기 작성(.env/DB 없이 autogenerate 불가)이므로, `news_analysis` 백필 마이그레이션과 동일한 형식으로 손으로 작성했다.

## 7. 변경 파일

| 파일 | 변경 |
|------|------|
| `app/db/orm_models/issue_docent.py` | market/sector/company id 컬럼 3개 + GIN 인덱스 3개 |
| `migrations/versions/f3a7c9d2e1b8_*.py` | 컬럼·인덱스 추가 + head 2개 병합 (신규) |
| `app/db/queries.py` | `ORIGIN_TO_MARKET_CODE`·`resolve_market_ids` 추가, `save_issue_docent` 시그니처 확장 |
| `services/pipeline/news_analyzer.py` | `_persist`에서 market 해소·docent 태그·LLM 제목 배선 |
| `services/analyzer/schemas.py` | `ContentDraft`·`ContentResult`에 `title` |
| `services/analyzer/content_generator.py` | `generate()`가 `title` 전달 |
| `prompts/news_generate.yaml` | title 출력 규칙·JSON·지시 추가 |
| `tests/test_news_analyzer.py`·`tests/test_content_generator.py` | market 해소 가짜·title 픽스처·단언 갱신 |

## 8. 검증

- `pytest` 전체 **214건 통과** (news_analyzer·content_generator 갱신 포함).
- `alembic heads` → 단일 head(`f3a7c9d2e1b8`) 확인. `alembic upgrade head --sql`(오프라인)로 head 병합과 `issue_docent` ALTER·GIN 인덱스 DDL 생성을 확인.
- DB 실제 적용(`alembic upgrade head`)·통합 실행(분석 러너로 origin=국내 이슈가 `market_ids=[KR]`·LLM 제목으로 적재되는지)은 DB 접속 후 수행한다.

## 9. 후속 과제

- 피드 조회 쿼리·API에서 `user_interest_*`와 `issue_docent.{market,sector,company}_ids`를 `&&`(배열 겹침)으로 매칭하는 엔드포인트 구현.
- 해외 종목 데이터가 들어오기 전까지 해외 이슈는 `GLOBAL` 하나로만 태깅된다 — NASDAQ·SP500·US_ETF로 세분 태깅하려면 해외 종목 유니버스 또는 분류 단계의 시장 식별 출력이 필요하다.
- **온보딩 정합성**: market 택소노미(6-종 reseed)·`search_companies`의 `MARKET_CODE_TO_EXCHANGES`(KOSPI/KOSDAQ) 정합은 main에서 이미 처리됨 — `resolve_market_ids`는 그 위에서 `CompanyEntity.market == Market.code` 조인으로 동작.
- LLM 제목 품질 평가(원문 복사율·금지 표현·길이) 지표화.

## 10. 참고 자료

- [10. 콘텐츠 파이프라인 구현 설계](./10-content-pipeline-implementation.md)
- [08. Pain → 콘텐츠 파이프라인](./08-pain-to-content-pipeline.md)
- `app/db/orm_models/issue_docent.py` · `app/db/queries.py` · `services/pipeline/news_analyzer.py`
