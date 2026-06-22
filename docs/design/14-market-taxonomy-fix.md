# 14. Market 택소노미 정합화 (코드 ↔ DB 불일치 해소)

> **작성자** Kim minkyoung · **작성일** 2026-06-22
>
> **범위** `markets` 마스터의 택소노미가 **코드/마이그레이션(`KR`/`OVERSEAS`)과 운영 DB(거래소·지수 6종)에서 어긋난** 문제의 기록과 해소. 온보딩 회사 필터 버그와 환경 drift의 원인이다. issue_docent의 market 태깅은 [13](./13-issue-docent-tagging-and-title.md)을 따른다.
>
> **결정**: 운영 DB의 **6-market(거래소·지수 단위)가 정본**. 시드 마이그레이션·ORM 주석·온보딩 회사 필터를 DB에 맞춘다.

---

## 목차

- [1. 증상](#1-증상) · [2. 근거](#2-근거) · [3. 근본 원인](#3-근본-원인)
- [4. 영향](#4-영향) · [5. 결정](#5-결정) · [6. 수정 항목](#6-수정-항목) · [7. 후속](#7-후속) · [8. 참고 자료](#8-참고-자료)

## 1. 증상

`markets` 테이블이 두 갈래로 갈라져 있었다.

| 위치 | 택소노미 |
|------|----------|
| 시드 마이그레이션 `211e9d09101d`·`Market` ORM 주석·온보딩 코드 | `KR`(국내) · `OVERSEAS`(해외) — 2개 |
| 운영 DB(실데이터) | `KOSPI` · `KOSDAQ` · `NASDAQ` · `SP500` · `US_ETF` · `GLOBAL` — 6개 (모두 `is_active=true`) |

## 2. 근거

- 시드 마이그레이션은 `{'code':'KR', is_active:True}`·`{'code':'OVERSEAS', is_active:False}` 두 행만 넣는다.
- 운영 DB는 id 3~8에 거래소·지수 6종을 갖는다(id가 1부터가 아니라 3부터인 것은 구 KR/OVERSEAS 행이 지워지고 재삽입됐음을 시사).
- 온보딩 회사 필터는 `MARKET_CODE_TO_EXCHANGES = {"KR": ("KOSPI","KOSDAQ")}`로 시장 코드를 거래소로 푼다 — `KR`만 알고 `KOSPI`/`NASDAQ` 등은 모른다.

## 3. 근본 원인

택소노미를 **2단계 큰 분류(국내/해외)**로 설계했다가, 운영에서 **거래소·지수 단위**로 더 잘게 재시드했으나 코드(시드·ORM·온보딩)가 따라오지 못했다. 마이그레이션이 데이터를 코드로 관리하는 단일 소스가 아니라, DB가 수동으로 앞서갔다.

## 4. 영향

- **온보딩 회사 필터 깨짐**: `GET /companies?market=<code>`에서 `market_code`가 `KOSPI` 등 실제 코드일 때 `MARKET_CODE_TO_EXCHANGES.get(code)`가 비어 **항상 빈 결과**. `KR`일 때만 동작했다.
- **환경 drift**: fresh DB(마이그레이션)는 KR/OVERSEAS 2개, 운영 DB는 6개 — 같은 코드가 환경마다 다른 데이터를 가리켜 재현·테스트가 어긋난다.
- **issue_docent market 태깅 의존**: [13](./13-issue-docent-tagging-and-title.md)의 `resolve_market_ids`는 운영 DB(6-market)엔 맞지만 fresh 시드(KR/OVERSEAS)엔 안 맞아, 시드 정합화가 선행돼야 한다.

## 5. 결정

운영 DB의 **6-market가 정본**이다. `markets`를 코드로 다시 단일 소스화하고, 온보딩 회사 필터를 거래소 직접 비교로 단순화한다.

| code | name_ko | name_en | is_active |
|------|---------|---------|-----------|
| `KOSPI` | 코스피 | KOSPI | true |
| `KOSDAQ` | 코스닥 | KOSDAQ | true |
| `NASDAQ` | 나스닥 | NASDAQ | true |
| `SP500` | S&P 500 | S&P 500 | true |
| `US_ETF` | 미국 ETF | US ETF | true |
| `GLOBAL` | 기타 해외 시장 | Other Global Markets | true |

## 6. 수정 항목

- **시드 정합화(신규 마이그레이션)**: 기존 `211e9d09101d` 시드는 이력이라 그대로 두고, 새 리비전이 `markets`를 6-market으로 reseed한다. `DELETE … code IN ('KR','OVERSEAS')` 후 `INSERT … ON CONFLICT (code) DO NOTHING`으로 **멱등** 적용 — 운영 DB(이미 6행)·fresh DB(KR/OVERSEAS) 양쪽을 같은 상태로 수렴시킨다. id는 환경별로 다를 수 있으나 FK가 id를 참조하므로 무방하다. (구 KR/OVERSEAS는 운영엔 없고 fresh엔 참조자가 없어 FK 위반 없음.)
- **온보딩 회사 필터**: `search_companies`에서 `MARKET_CODE_TO_EXCHANGES` 간접 매핑을 제거하고 `CompanyEntity.market == market_code`로 직접 비교한다. 종목 유니버스는 국내(KOSPI/KOSDAQ)뿐이라, 해외 4종은 빈 결과로 수렴하는 게 정상이다. 상수 `MARKET_CODE_TO_EXCHANGES`는 유일 사용처가 사라져 제거.
- **주석·설명**: `Market` ORM docstring·`code` 주석, `masters` 라우터 `market` Query 설명을 6-market 기준으로 갱신.
- `resolve_market_ids`([13](./13-issue-docent-tagging-and-title.md))는 이미 `CompanyEntity.market == Market.code` 조인이라 정합 — 변경 없음.

## 7. 후속

- 앞으로 `markets`·`sectors` 같은 **마스터 시드는 마이그레이션을 단일 소스**로 관리하고, DB 수동 변경을 지양한다(또는 변경 시 동등한 마이그레이션을 함께 커밋).
- 해외 종목 유니버스가 없는 동안 `NASDAQ`/`SP500`/`US_ETF`는 온보딩 노출은 되나 회사 목록·issue_docent 태깅에서는 비게 된다 — 노출 정책(비활성 처리 등) 별도 검토.

## 8. 참고 자료

- [13. Issue Docent 관심사 태깅 · LLM 제목 생성](./13-issue-docent-tagging-and-title.md)
- `migrations/versions/211e9d09101d_add_user_market_user_interest_tables.py` (구 시드)
- `app/db/queries.py`(`search_companies`) · `app/db/orm_models/market.py` · `app/api/routers/masters.py`
