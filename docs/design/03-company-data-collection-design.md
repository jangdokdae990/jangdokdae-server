# 기업 데이터 수집 기획서

> **작성자** Kim minkyoung · **작성일** 2026-05-28 · **개정일** 2026-06-08 — 구현 반영 (dart-fss → DART 구조화 API, 주가·환율 on-demand 전환, 청크 타입·스키마 정정)
>
> **범위** 기업 데이터 수집 → DB 적재 / on-demand 조회 → RAG 소스 준비
>
> **관련 문서**
>
> - [파이프라인 오케스트레이션](./01-pipeline-orchestration-design.md)
> - [임베딩·클러스터링 기획서](./05-embedding-clustering-design.md)

> **개정 메모 (2026-06-08)**  
> 본 문서는 실제 구현(`services/collector/*`)과 다음 결정을 반영해 개정되었다.
> - **재무제표**는 `dart-fss` 라이브러리가 아니라 **DART 구조화 재무 API(`fnlttSinglAcntAll.json`)** 를 직접 사용한다.
> - **주가·환율**은 매일 적재하지 않고 **필요 시점에 API로 조회(on-demand)** 한다. 시계열 추세 분석을 로컬에서 반복하지 않으므로 상시 적재의 실익이 적다. 단 분석에 사용한 값은 분석 산출물에 스냅샷으로 보존한다.
> - **거시지표·공시·재무·사업보고서 청크**는 적재 유지(RAG·추세 조회 대상).
> - 사업보고서 텍스트 청크 타입은 `business_summary` / `director_analysis` / `audit_opinion`이다.

---

## 목차

- [1. 목적](#1-목적)
- [2. RAG · pgvector 필요성](#2-rag-·-pgvector-필요성)
- [3. 수집 대상 분류](#3-수집-대상-분류)
- [4. API별 상세](#4-api별-상세)
- [5. DB 적재 방법론](#5-db-적재-방법론)
- [6. DB 스키마](#6-db-스키마)
- [7. 수집 파이프라인 아키텍처](#7-수집-파이프라인-아키텍처)
- [8. 에러 처리 전략](#8-에러-처리-전략)
- [9. API 키 목록](#9-api-키-목록)
- [10. 구현 로드맵](#10-구현-로드맵)

---

## 1. 목적

### 1.1 기업 데이터가 분석 파이프라인에서 하는 역할

분석 파이프라인(`app/llm/graph.py`)은 LangGraph 기반으로 4개의 Chain이 순차 실행된다.

```
FilterChain → EntityExtractionChain → ImpactAnalysisChain → ExplanationChain
```

기업 데이터 수집의 핵심 목적은 `ImpactAnalysisChain`에 기업 컨텍스트를 주입하는 것이다.

**파이프라인 input에서의 역할:**

```python
{
    "news_title": str,
    "news_content": str,
    "news_url": str,
    "source": str,
    "related_companies": str,  # ← 기업 데이터 수집의 최종 산출물 (RAG 검색 결과)
}
```

`related_companies`는 `EntityExtractionChain`이 뉴스에서 기업명을 추출한 뒤, 해당 기업의 사업보고서·재무정보를 pgvector로 검색해 문자열로 구성한 것이다.

**분석 파이프라인에서의 위치:**

```
[수집 — 이 문서의 범위]
  공시(DART list.json)
  재무제표(DART fnlttSinglAcntAll)  →  DB 적재  →  임베딩(pgvector)  →  ImpactAnalysisChain
  사업보고서 텍스트(DART document.xml)                                   (related_companies)
  거시지표(ECOS)

  주가·환율(FinanceDataReader)  →  on-demand 조회 →  분석 시점 프롬프트 주입(보조 컨텍스트)
```

### 1.2 기업 데이터 종류와 용도 요약

| 데이터 | 출처 | 적재/조회 | 주요 용도 |
|--------|------|----------|----------|
| 기업 마스터(유니버스) | DART corpCode.xml + PyKRX | 적재 (`company_entities`) | 수집 대상 종목·Entity Linking 기준 |
| 공시 | DART REST API (`list.json`) | 적재 (메타데이터, 본문은 후속 fetch) | 분석 파이프라인 input + RAG 소스 |
| 사업보고서 재무제표 | **DART `fnlttSinglAcntAll.json`** | 적재 (`financial_statements`) | RAG 소스 (재무 수치 구조화) |
| 사업보고서 텍스트 | **DART `document.xml` + 섹션 청킹** | 적재 (`report_chunks`) | RAG 소스 (사업 내용·경영진단·감사의견 청킹) |
| 주가 (국내) | FinanceDataReader | **on-demand 조회** | 분석 보조 컨텍스트 |
| 주가 (해외) | yfinance | 미구현 (Phase 2) | 분석 보조 컨텍스트 (대형주) |
| 환율 | FinanceDataReader | **on-demand 조회** | 거시 이슈 분석 컨텍스트 |
| 거시지표 (금리·CPI·M2) | 한국은행 ECOS API | 적재 (`market_indicators`) | 거시 이슈 분석 컨텍스트 |

> **on-demand 데이터의 위치**: 주가·환율은 임베딩/클러스터링 대상이 아니라 분석 시점에 프롬프트로 주입되는 보조 컨텍스트다. 분석 대상은 뉴스에서 추출된 소수의 related company뿐이고, FinanceDataReader가 기간 파라미터로 과거 구간을 언제든 재조회할 수 있으므로 상시 적재 대신 호출 시점 조회한다. 향후 Phase 2에서 전종목 추세 분석을 도입하면 적재로 전환할 수 있다.

---

## 2. RAG · pgvector 필요성

### 2.1 pgvector가 필요한 이유

프로젝트 tech stack에 이미 Neon(PostgreSQL)이 포함되어 있으며, Neon은 pgvector를 기본 지원한다. **별도 벡터 DB(Pinecone, Weaviate 등) 없이** 기존 DB에서 벡터 검색이 가능하다.

```sql
-- Neon에서 pgvector 활성화 (1회만 실행)
CREATE EXTENSION IF NOT EXISTS vector;
```

**pgvector 사용처:**

| 용도 | 설명 |
|------|------|
| **유사 뉴스 중복 제거** | 같은 이슈를 다룬 기사를 cosine similarity로 묶어 대표 1건만 분석 |
| **뉴스 클러스터링** | 오늘의 뉴스를 주제별로 묶어 Issue Docent 생성 |
| **RAG 검색** | 기업 사업보고서 청크 중 관련 섹션을 벡터 검색으로 찾아 LLM에 주입 |
| **관련 과거 이슈 검색** | "이 기사와 유사한 과거 이슈" 검색 |

### 2.2 RAG가 필요한 이유

`ImpactAnalysisChain`이 뉴스 본문과 entity 추출 결과만으로 영향도를 판단하면 기업 컨텍스트가 없어 분석이 얕다.

**RAG 없을 때 vs 있을 때 비교:**

```
RAG 없음:
  뉴스: "삼성전자가 반도체 감산을 발표했다"
  → 영향도: high (왜 high인지 근거 빈약)

RAG 있음:
  뉴스: "삼성전자가 반도체 감산을 발표했다"
  + RAG 검색 결과: 삼성전자 반도체 부문 매출 비중 60%, 최근 분기 영업이익 -4조
  → "반도체 부문이 전체 매출의 60%이고 이미 적자인 상황에서
     감산은 단기 비용 절감이나 중장기 공급 조정으로 해석 가능하다"
  → 훨씬 구체적이고 주린이가 이해하기 쉬운 분석
```

**RAG 활용 흐름:**

```
① 뉴스에서 기업명 추출 (EntityExtractionChain)
② 해당 기업의 사업보고서 청크를 pgvector로 검색
   → "삼성전자 반도체 사업 현황", "삼성전자 재무요약" 청크 반환
③ ImpactAnalysisChain 호출 시 related_companies 파라미터에 포함
④ 더 정확한 영향도 분석 + 주린이 해설 생성
```

### 2.3 LangChain PGVector 연동 코드

Neon은 LangChain `PGVector` 래퍼와 바로 연동된다.

```python
from langchain_postgres.vectorstores import PGVector
from app.core.config import settings

# 벡터스토어 초기화
vectorstore = PGVector(
    embeddings=embedding_model,
    collection_name="report_chunks",
    connection=settings.DATABASE_URL,
)

# 사업보고서 청크 저장
vectorstore.add_texts(
    texts=["삼성전자 반도체 부문은 전체 매출의 60%를 차지한다..."],
    metadatas=[{"corp_code": "00126380", "chunk_type": "business_summary"}],
)

# 관련 청크 검색
docs = vectorstore.similarity_search("삼성전자 반도체 매출", k=3)

# related_companies 문자열 구성
related_companies = "\n\n".join([doc.page_content for doc in docs])
```

별도 인프라 없이 기존 Neon DB 하나로 관계형 데이터 + 벡터 검색을 모두 처리한다.

---

## 3. 수집 대상 분류

| 분류 | 세부 항목 | 출처 | 수집/조회 방식 | 분석 파이프라인 역할 |
|------|----------|------|----------|---------------------|
| **기업 마스터** | 종목·DART코드·섹터·마켓 | DART corpCode.xml + PyKRX | 주기 동기화 (적재) | 수집 대상 유니버스 + Entity Linking |
| **공시** | 정기보고서(A), 주요사항(B) | DART `list.json` | 이벤트 발생 시 (적재, 메타만) | input + RAG 소스 |
| **재무제표** | 매출·영업이익·순이익·자산총계 | DART `fnlttSinglAcntAll.json` | 분기 1회 (적재) | **RAG 소스 핵심** |
| **사업보고서 텍스트** | 사업의 내용·경영진단·감사의견 | DART `document.xml` | 분기 1회 (적재, 청킹) | **RAG 소스 핵심** |
| **주가 (국내)** | 일봉(OHLCV) | FinanceDataReader | **on-demand 조회** | 분석 보조 컨텍스트 |
| **주가 (해외)** | 일봉, 재무제표 | yfinance | **미구현 (Phase 2)** | 분석 보조 컨텍스트 |
| **시총·외국인 보유** | 시가총액, 외국인 보유 | pykrx | **미구현 (Phase 2)** | 분석 보조 컨텍스트 |
| **환율** | USD/JPY/EUR/CNY/KRW | FinanceDataReader | **on-demand 조회** | 거시 이슈 분석 컨텍스트 |
| **거시지표** | 기준금리, CPI, M2 | 한국은행 ECOS | 월별 (적재) | 거시 이슈 분석 컨텍스트 |

---

## 4. API별 상세

### 4.1 DART REST API — 공시 수집

- **URL**: [opendart.fss.or.kr](https://opendart.fss.or.kr)
- **비용**: 완전 무료, API 키 즉시 발급
- **용도**: 공시 **메타데이터** 수집 (접수번호·제목·공시일·기업 정보)
- **구현**: [`services/collector/dart_collector.py`](../../services/collector/dart_collector.py) — `list.json`으로 (기업 × 공시유형) 단위 병렬 수집, `total_page` 페이지네이션, `status="013"`(데이터 없음)은 정상 종료

> **본문(content) 수집 시점**: 수집 단계에서는 공시 **메타데이터만** 저장하고 `content=NULL`로 둔다. 본문 원문은 분석 단계에서 필요한 공시에 한해 `document.xml`로 별도 fetch한다. 추적 기업의 모든 공시 본문을 미리 받아 저장하는 것은 낭비이므로, "분석 대상으로 선정된 공시"만 본문을 채운다.

#### 수집할 공시 유형 코드표

| 유형 코드 | 설명 | 분석 파이프라인 활용 |
|----------|------|---------------------|
| `A` | 사업보고서, 분기보고서, 반기보고서 | RAG 소스 (텍스트 청킹) |
| `B` | 유상증자, 합병, 주요 계약 (주요사항보고서) | 분석 파이프라인 직접 input |

#### 코드 예시

```python
import httpx

DART_BASE_URL = "https://opendart.fss.or.kr/api"

async def fetch_disclosures(corp_code: str, disclosure_type: str = "B") -> list[dict]:
    """특정 기업의 공시 목록 조회"""
    url = f"{DART_BASE_URL}/list.json"
    params = {
        "crtfc_key": settings.DART_API_KEY,
        "corp_code": corp_code,
        "pblntf_ty": disclosure_type,
        "page_no": 1,
        "page_count": 100,
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        return data.get("list", [])

async def fetch_disclosure_content(rcept_no: str) -> str:
    """공시 원문 본문 조회"""
    url = f"{DART_BASE_URL}/document.xml"
    params = {
        "crtfc_key": settings.DART_API_KEY,
        "rcept_no": rcept_no,
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.text  # XML 형식 반환
```

> **참고**: DART 공시는 공공 데이터이므로 본문 전체를 DB에 저장해도 저작권 리스크 없음. (뉴스와 다른 점)

---

### 4.2 DART 구조화 재무 API — 재무제표

**dart-fss 대신 DART `fnlttSinglAcntAll.json`(단일회사 전체 재무제표 API)을 직접 사용한다.** DART가 이미 재무제표를 구조화 JSON으로 제공하므로, HTML/XBRL 파싱 라이브러리(dart-fss) 없이도 핵심 수치를 받을 수 있다. 외부 라이브러리 의존을 줄이고, 비동기 httpx로 다른 수집기와 동일한 패턴을 유지한다.

| 항목 | dart-fss 라이브러리 | **DART fnlttSinglAcntAll.json (채택)** |
|------|------------------------|--------------|
| 재무제표 파싱 | DataFrame 자동 반환 | 구조화 JSON 직접 파싱 (계정 4종만) |
| 외부 의존성 | dart-fss 추가 필요 | httpx만 (기존 의존성) |
| 실행 방식 | 동기 (to_thread 필요) | 비동기 (다른 수집기와 일관) |
| 커버리지 | 전체 계정 | 핵심 4계정(매출·영업이익·순이익·자산총계)으로 한정 |
| **결론** | 미사용 | **핵심 재무 수치 수집에 사용** |

- **구현**: [`services/collector/financial_collector.py`](../../services/collector/financial_collector.py)
- **연결(CFS) 우선, 개별(OFS) 폴백**: 종속회사가 없어 연결재무제표를 작성하지 않는 기업은 CFS가 `013`(데이터 없음)이므로, CFS 실패 시 OFS로 폴백해 수치 누락을 방지한다.
- **손익 항목 재무제표 구분(`sj_div`)**: 회사에 따라 `IS`(손익) 또는 `CIS`(포괄손익)에 보고되므로 둘 다 허용한다.
- **`reprt_code`**: 사업보고서=`11011`(분기 4), 1·반기·3분기=`11013`/`11012`/`11014`.

#### 코드 예시

```python
DART_FS_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

# 지표 → (account_nm 후보, 허용 sj_div)
_INCOME = frozenset({"IS", "CIS"})
_METRICS = {
    "revenue":          (("매출액", "수익(매출액)", "영업수익"), _INCOME),
    "operating_income": (("영업이익", "영업이익(손실)"),          _INCOME),
    "net_income":       (("당기순이익", "당기순이익(손실)"),       _INCOME),
    "total_assets":     (("자산총계",),                          frozenset({"BS"})),
}

async def fetch_accounts(client, corp_code, bsns_year, reprt_code, fs_div):
    params = {
        "crtfc_key": settings.opendart_api_key,
        "corp_code": corp_code, "bsns_year": str(bsns_year),
        "reprt_code": reprt_code, "fs_div": fs_div,  # "CFS" | "OFS"
    }
    data = (await client.get(DART_FS_URL, params=params)).json()
    return data["list"] if data.get("status") == "000" else None
```

**역할 분담:**

```
DART list.json            →  공시 목록(메타데이터) 수집
DART fnlttSinglAcntAll     →  재무제표 핵심 수치 구조화 저장
DART document.xml          →  사업보고서 본문 텍스트 → 섹션 청킹 (§4.2.1)
```

#### 4.2.1 사업보고서 텍스트 청킹 — DART document.xml

재무 **수치**는 `fnlttSinglAcntAll`로 받고, 사업보고서 **본문 텍스트**는 `document.xml`(ZIP) API로 받아 섹션 단위로 청킹한다.

- **구현**: 수집 [`services/collector/report_collector.py`](../../services/collector/report_collector.py) + 파싱 [`services/preprocessor/company_preprocessor.py`](../../services/preprocessor/company_preprocessor.py)
- **흐름**: `list.json`으로 최신 사업보고서 `rcept_no` 조회(정정 공시 대비 `rcept_dt` 최신본 선택) → `document.xml`로 ZIP 다운로드 → XML 텍스트 추출 → `parse_report_sections()`로 3개 대섹션을 소제목(subsection) 단위로 분할.
- **추출 섹션 → chunk_type**:

| 보고서 대섹션 | chunk_type |
|------|------------|
| `II. 사업의 내용` | `business_summary` |
| `IV. 이사의 경영진단 및 분석의견` | `director_analysis` |
| `V. 회계감사인의 감사의견 등` | `audit_opinion` |

---

### 4.3 주가 데이터 — FinanceDataReader (on-demand)

**적재하지 않고 분석 시점에 조회한다.** 주가는 임베딩/클러스터링 대상이 아니라 분석 프롬프트에 텍스트로 주입되는 보조 컨텍스트이고, FinanceDataReader가 기간 파라미터로 과거 구간을 언제든 재조회할 수 있으므로 매 거래일 적재의 실익이 적다. (결정 근거는 [§5.1](#51-데이터-유형별-전략) 참조)

- **현재 구현**: [`services/collector/stock_collector.py`](../../services/collector/stock_collector.py) — FinanceDataReader로 국내 일봉(OHLCV)을 종목 단위 병렬(`to_thread`) 수집. 결측 OHLCV 행은 스킵.
- **사용 방식**: 위 수집기는 **on-demand 조회 함수**로 사용한다(분석 단계에서 related company의 최근 N일 구간을 호출). 반복 호출 시 단기 캐시(`requests-cache` 등)를 권장한다.
- **미구현 (Phase 2)**: pykrx 시총·외국인 보유, yfinance 해외 주가·재무제표. 전종목 추세 분석을 도입하는 Phase 2에서 적재 방식과 함께 추가한다.

#### 역할 분담 (목표 구성)

| 라이브러리 | 용도 | 상태 |
|-----------|------|------|
| **FinanceDataReader** | 국내+해외 주가, 환율, 지수 (기본) | ✅ 구현 (on-demand) |
| **pykrx** | 국내 시총, 외국인 보유 (보조) | ⏳ Phase 2 (단, 섹터·마켓 동기화엔 이미 사용 — §7.5) |
| **yfinance** | 해외 대형주 주가·재무제표 | ⏳ Phase 2 |

#### 코드 예시 (on-demand 조회)

```python
import FinanceDataReader as fdr

# 분석 시점에 related company의 최근 구간만 조회 (DB 적재 없음)
df = fdr.DataReader("005930", "2024-01-01")    # 삼성전자 일봉
recent = df.tail(20)                            # 최근 20거래일 → 프롬프트용 요약
```

> **on-demand 운영 주의**: ① 추세(이동평균·변동성) 계산을 위해 과거 N일을 매번 호출하므로 단기 캐시를 붙인다. ② "이 분석은 그날의 그 주가를 근거로 했다"는 재현성이 필요하면, 분석 산출물에 사용한 값을 **스냅샷으로 함께 저장**한다(실시간 API는 과거 시점의 당시 값을 항상 보장하지 않음).
>
> **yfinance 주의사항(Phase 2)**: 비공식 API로 rate limit이 있다. `requests-cache`와 함께 사용하고 요청 간격을 둬야 한다. 한국 소형주 커버리지가 부족하므로 국내 주가는 FinanceDataReader 우선.

---

### 4.4 환율 — FinanceDataReader (on-demand)

주가와 같은 라이브러리로 환율도 처리하며, 주가와 동일하게 **적재하지 않고 on-demand로 조회**한다(통화 4종뿐이라 호출 비용이 무시할 수준). 별도 환율 API를 추가하지 않는다.

- **구현**: [`services/collector/macro_collector.py`](../../services/collector/macro_collector.py)의 `collect()` — USD/JPY/EUR/CNY ÷ KRW를 통화 단위 병렬(`to_thread`) 수집, NaN(휴장일) 행은 스킵. (같은 파일의 `collect_ecos()`는 §4.5의 적재 대상 거시지표를 담당)

```python
import FinanceDataReader as fdr

EXCHANGE_RATES = (("USD/KRW", "USD"), ("JPY/KRW", "JPY"),
                  ("EUR/KRW", "EUR"), ("CNY/KRW", "CNY"))

# 분석 시점에 필요한 통화·구간만 조회
df = fdr.DataReader("USD/KRW", start_date)
```

**선택 이유**: 실무에서 별도 환율 API를 추가하는 사례가 거의 없다. FinanceDataReader가 환율·주가를 통합 제공하므로 수집기 코드를 하나로 유지한다.

---

### 4.5 거시지표 — 한국은행 ECOS API

- **URL**: [ecos.bok.or.kr/api](https://ecos.bok.or.kr/api/)
- **비용**: 무료
- **이유**: FinanceDataReader는 환율·지수 위주. 기준금리·CPI·M2 같은 거시지표는 한국은행 ECOS만 제공

#### 수집 통계표 코드표 (구현 기준)

ECOS에서는 **월별 거시지표 3종만 적재**한다. 환율은 §4.4 FinanceDataReader(on-demand)가 담당하고, 코스피 지수는 현재 미수집이다.

| 지표 | 통계표 코드 | 항목 코드 | 주기 | 분석 활용 |
|------|------------|----------|------|----------|
| 기준금리 | `722Y001` | `0101000` | `M` | 금리 변동 이슈 분석 |
| 소비자물가지수(CPI) | `901Y009` | `0` (총지수) | `M` | 인플레이션 이슈 분석 |
| M2 통화량(평잔, 원계열) | `161Y006` | `BBHA00` | `M` | 유동성 분석 |

> **정정 사항**: ① M2 통계표 `101Y004`는 폐지된 구 표 → 현재는 `161Y006`. ② ECOS 주기 코드는 `M`(월)이다(이전 표기 `MM`은 오기). ③ 환율(`731Y003`)·코스피(`802Y001`)는 ECOS 적재 대상에서 제외(환율은 FinanceDataReader on-demand).

#### 코드 예시

```python
import httpx

ECOS_BASE_URL = "https://ecos.bok.or.kr/api"

async def fetch_ecos_indicator(
    stat_code: str,
    item_code: str,
    start_date: str,
    end_date: str,
    period_type: str = "M",  # "D"(일) | "M"(월) | "Q"(분기) | "A"(년)
) -> list[dict]:
    """한국은행 ECOS API로 거시지표 수집"""
    url = (
        f"{ECOS_BASE_URL}/StatisticSearch/{settings.ECOS_API_KEY}/json/kr/1/100/"
        f"{stat_code}/{period_type}/{start_date}/{end_date}/{item_code}"
    )
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
        return data["StatisticSearch"]["row"]

# 사용 예시 — 기준금리 수집
rows = await fetch_ecos_indicator(
    stat_code="722Y001",
    item_code="0101000",
    start_date="202401",
    end_date="202412",
    period_type="M",
)
```

---

## 5. DB 적재 방법론

### 5.1 데이터 유형별 전략

**핵심 판단 기준**: "이 데이터로 **시계열 추세 분석을 로컬에서 반복**하는가?" — 그렇다면 적재, 아니면 on-demand.

| 유형 | 패턴 | 전략 | 근거 |
|------|------|------|----------|
| **주가** | 매 거래일 | **on-demand 조회** | 임베딩 대상 아님, API 재조회 가능, 대상 종목 소수 |
| **환율** | 매 영업일 | **on-demand 조회** | 통화 4종, 호출 비용 무시 가능 |
| **거시지표** | 월별 | 적재 — `(indicator_type, currency, date)` UPSERT | 월 1회로 양 적고 추세 조회 잦음, ECOS 호출 상대적 느림 |
| **공시** | 이벤트 발생 시 | 적재 (메타만) — `rcept_no` unique | input + RAG, 본문은 분석 단계 fetch |
| **재무제표** | 분기 1회 | 적재 — `(corp_code, year, quarter)` UPSERT | RAG 소스, 구조화 수치 |
| **사업보고서 텍스트** | 분기 1회 | 적재 — **섹션 청킹** 후 임베딩 | **RAG 소스 핵심**, pgvector 검색 대상 |

**on-demand 데이터 (주가·환율)**:
- DB에 적재하지 않고 분석 시점에 FinanceDataReader로 조회한다.
- 반복 호출에는 단기 캐시를 붙이고, 재현성이 필요한 값은 분석 산출물에 스냅샷으로 보존한다.
- 현재 `stock_collector`·`macro_collector.collect()`는 이 조회 함수로 사용한다. (적재 파이프라인에는 넣지 않음)

**적재 시계열 데이터 (거시지표)**:
- Append-only 패턴. 기존 행 수정 없음. 중복은 `ON CONFLICT DO NOTHING`으로 처리(멱등).
- `currency`가 NULL인 ECOS 지표도 멱등 UPSERT 되도록 unique 제약에 `NULLS NOT DISTINCT`(PG15+)를 적용한다.

**이벤트 데이터 (공시)**:
- DART 접수번호(`rcept_no`)가 고유 식별자. 같은 공시를 두 번 수집해도 `rcept_no` unique로 자동 차단.

### 5.2 전체 종목 vs 관심 종목 (Phase별 확장)

코스피+코스닥 전체 종목(~2,500개) 적재 용량 추정:

```
2,500종목 × 252거래일 = 630,000 rows/년
5년 히스토리 = 3,150,000 rows
→ PostgreSQL 충분히 감당 가능
```

하지만 MVP 단계에서 전체를 쌓을 필요는 없다.

| Phase | 대상 | 이유 |
|-------|------|------|
| **Phase 1 (MVP)** | 사용자 관심 종목 + 코스피200 대형주 | 빠른 시작, 핵심 종목 커버 |
| **Phase 2 (성장)** | 코스피·코스닥 전체 종목 | 서비스 확장 시 전종목 분석 |

### 5.3 Backfill vs Incremental — 적재 대상에만 적용

서비스 시작 시 과거 데이터가 없으면 LLM이 "최근 흐름"을 참고할 수 없다. 단 **이 분리는 "적재하는 데이터"에만 해당한다.** 주가·환율은 on-demand 조회로 전환했으므로 backfill 대상이 아니다(필요 구간을 그때 호출).

```
scripts/                             ← 최초 1회만 실행 (Backfill) — 적재 대상만
  ├── backfill_market_indicators.py   # 과거 N년치 금리·CPI·M2 (ECOS)
  └── backfill_disclosures.py         # 과거 N년치 공시·재무·사업보고서

(Incremental)                        ← Airflow DAG가 주기 실행
  ├── 거시지표: 월별
  └── 공시·재무·사업보고서: 일별/분기
```

**분리 이유**: 한 번 실행하는 코드와 주기 실행하는 코드가 섞이면 실수로 재실행 시 데이터 중복·오염 위험이 있다. `scripts/`는 명시적으로 수동 실행해야 하는 코드임을 디렉토리 위치로 표현한다.

#### 뉴스 수집과의 차이 — "backfill이 성립하는가"

> 질문: "backfill vs incremental은 뉴스 수집도 동일하지 않은가?"

**멱등 UPSERT 원칙은 공통이지만, backfill/incremental *분리*는 뉴스에 적용되지 않는다.**

| | 기업 데이터 (공시·재무·거시) | 뉴스 (RSS) |
|---|------|------|
| 과거 일괄 수집 | **가능** — API가 기간 파라미터 지원 (`bgn_de~end_de`, `start_date`) | **불가능** — RSS 피드는 최근 N건만 노출, 과거 기사 소스 없음 |
| backfill 존재 이유 | 시작 시 "최근 흐름" 히스토리 필요 | backfill할 데이터 소스 자체가 없음 |
| 결론 | scripts/(backfill) ↔ DAG(incremental) 분리 | **incremental만 존재** (하루 2회 폴링) |

즉 뉴스는 RSS 특성상 첫 실행이든 주기 실행이든 "최근 피드 폴링"이라는 동일 로직이라 분리할 대상이 없다. backfill/incremental 분리는 **과거를 일괄로 받을 수 있는 데이터**(공시·재무·거시지표)에 한정된다.

### 5.4 사업보고서 청킹 전략

사업보고서 원문은 수십~수백 페이지다. 그대로 하나의 TEXT 컬럼에 저장하면 LLM 컨텍스트 한도를 초과한다.

**방법 A — 섹션 단위 청킹 (RAG 소스용)**

DART 사업보고서의 표준 대섹션 제목으로 분할하고, 각 대섹션을 소제목(subsection) 단위로 다시 나눠 저장한다. 구현은 [`parse_report_sections()`](../../services/preprocessor/company_preprocessor.py).

| chunk_type | 원본 대섹션 | RAG 검색 쿼리 예시 |
|------------|------|------------------|
| `business_summary` | `II. 사업의 내용` | "삼성전자 주요 사업" |
| `director_analysis` | `IV. 이사의 경영진단 및 분석의견` | "삼성전자 실적 평가·전망" |
| `audit_opinion` | `V. 회계감사인의 감사의견 등` | "삼성전자 감사의견" |

```python
# parse_report_sections() 반환 형태:
# {"business_summary": [{"subsection": "1. 사업의 개요", "content": "..."}, ...], ...}
sections = parse_report_sections(xml_text)

for chunk_type, items in sections.items():
    for item in items:
        if not item["content"].strip():
            continue
        chunk = ReportChunk(
            corp_code=corp_code, corp_name=corp_name,
            report_year=year, rcept_no=rcept_no,
            chunk_type=chunk_type,
            subsection=item["subsection"],   # 소제목 (없으면 "")
            content=item["content"],
            # embedding은 services/embedder에서 별도 생성
        )
        db.add(chunk)
```

**방법 B — 재무 수치 구조화 저장 (DART `fnlttSinglAcntAll`)**

재무 수치는 텍스트 청킹 대신 숫자 컬럼으로 구조화 저장한다. LLM이 숫자를 직접 읽기보다 포맷된 문자열로 받는 것이 더 정확하다.

```python
# FinancialStatement 레코드 → RAG 텍스트 변환
def format_financial_context(fs: FinancialStatement) -> str:
    return (
        f"{fs.corp_name} {fs.year}년 {fs.quarter}분기 재무 현황\n"
        f"- 매출액: {fs.revenue / 1e8:.0f}억원\n"
        f"- 영업이익: {fs.operating_income / 1e8:.0f}억원\n"
        f"- 당기순이익: {fs.net_income / 1e8:.0f}억원\n"
        f"- 자산총계: {fs.total_assets / 1e8:.0f}억원"
    )
```

**두 방법 병행**: 재무 수치는 `FinancialStatement` 구조화 테이블, 텍스트(사업의 내용·경영진단·감사의견)는 `ReportChunk` 청킹 후 임베딩 저장.

### 5.5 UPSERT 중복 방지 전략

모든 적재는 `ON CONFLICT DO NOTHING`으로 upsert → 재실행해도 안전 (멱등성).

실제 구현은 [`services/collector/tools/save_tool.py`](../../services/collector/tools/save_tool.py)가 테이블별 충돌 키를 캡슐화한다. (주가 `upsert_stock_prices`는 on-demand 전환 후 backfill/Phase 2용으로만 남는다.)

```python
# 주가: (stock_code, date) 복합 유니크
__table_args__ = (UniqueConstraint("stock_code", "date"),)

# 공시: DART 접수번호 유니크
rcept_no = Column(String(20), unique=True)

# 거시지표: (indicator_type, currency, date) 복합 유니크 — currency NULL 멱등 위해 NULLS NOT DISTINCT
__table_args__ = (UniqueConstraint("indicator_type", "currency", "date",
                                   postgresql_nulls_not_distinct=True),)

# UPSERT 실행 패턴 (save_tool._upsert)
from sqlalchemy.dialects.postgresql import insert as pg_insert

async def upsert_market_indicators(db, records: list[dict]) -> int:
    stmt = pg_insert(MarketIndicator).values(records)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["indicator_type", "currency", "date"])
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount
```

---

## 6. DB 스키마

### Disclosure — DART 공시

```python
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from pgvector.sqlalchemy import Vector
from app.db.base import Base

class Disclosure(Base):
    __tablename__ = "disclosures"

    id               = Column(Integer, primary_key=True)
    rcept_no         = Column(String(20), unique=True, nullable=False)  # DART 접수번호 (중복 방지 키)
    title            = Column(String(500), nullable=False)
    content          = Column(Text, nullable=True)                      # 공시 본문 (공공 데이터, 저장 가능)
    corp_name        = Column(String(200), nullable=False)
    corp_code        = Column(String(20), nullable=False)               # DART 기업 고유코드
    stock_code       = Column(String(20), nullable=True)                # 종목 코드 (상장사만)
    disclosure_type  = Column(String(50), nullable=False)               # "A" | "B"
    disclosed_at     = Column(DateTime(timezone=False), nullable=False) # 공시 일시 (KST naive)
    is_analyzed      = Column(Boolean, server_default=text("false"), default=False, nullable=False)  # 분석 처리 여부
    created_at       = Column(DateTime(timezone=False), server_default=KST_NOW, nullable=False)
    embedding        = Column(Vector(768), nullable=True)               # pgvector — 유사도 검색
```

### StockPrice — 주가 시계열 (현재 on-demand, 적재 미사용 / backfill·Phase 2 대비 정의)

> 주가는 on-demand 조회로 전환했으므로 평시 적재 대상이 아니다. 본 스키마는 backfill·Phase 2(전종목 추세 분석) 전환 시를 위해 정의만 유지한다.

```python
from sqlalchemy import Column, Integer, String, Float, BigInteger, Date, DateTime, UniqueConstraint

class StockPrice(Base):
    __tablename__ = "stock_prices"

    id         = Column(Integer, primary_key=True)
    stock_code = Column(String(20), nullable=False)      # 종목 코드 (예: "005930")
    name       = Column(String(100), nullable=False)     # 종목명 (예: "삼성전자")
    open       = Column(Float, nullable=False)
    high       = Column(Float, nullable=False)
    low        = Column(Float, nullable=False)
    close      = Column(Float, nullable=False)
    volume     = Column(BigInteger, nullable=False)
    market_cap = Column(BigInteger, nullable=True)       # 시가총액 (pykrx 보완 — Phase 2)
    date       = Column(Date, nullable=False)            # 거래일
    created_at = Column(DateTime(timezone=False), server_default=KST_NOW, nullable=False)

    __table_args__ = (UniqueConstraint("stock_code", "date", name="uq_stock_code_date"),)
```

### MarketIndicator — 거시지표 (ECOS 적재)

> 적재 대상은 ECOS 월별 지표(`interest_rate`·`cpi`·`m2`)다. `exchange_rate`는 스키마상 표현 가능하나 환율은 on-demand로 전환했으므로 평시 적재하지 않는다.

```python
class MarketIndicator(Base):
    __tablename__ = "market_indicators"

    id             = Column(Integer, primary_key=True)
    indicator_type = Column(String(50), nullable=False)   # "interest_rate" | "cpi" | "m2" | ("exchange_rate")
    currency       = Column(String(10), nullable=True)    # 환율만 값, ECOS 지표는 NULL
    value          = Column(Float, nullable=False)
    date           = Column(Date, nullable=False)
    created_at     = Column(DateTime(timezone=False), server_default=KST_NOW, nullable=False)

    # currency가 NULL인 ECOS 지표도 멱등 UPSERT 되도록 NULLS NOT DISTINCT (PG15+)
    __table_args__ = (
        UniqueConstraint("indicator_type", "currency", "date",
                         name="uq_market_indicator", postgresql_nulls_not_distinct=True),
    )
```

### FinancialStatement — 재무제표 (DART fnlttSinglAcntAll)

```python
class FinancialStatement(Base):
    __tablename__ = "financial_statements"

    id               = Column(Integer, primary_key=True)
    corp_code        = Column(String(20), nullable=False)
    corp_name        = Column(String(200), nullable=False)
    rcept_no         = Column(String(20), nullable=True)    # 원천 사업보고서 접수번호 (disclosures·report_chunks 연결 추적 키)
    year             = Column(Integer, nullable=False)
    quarter          = Column(Integer, nullable=False)      # 1~4 (사업보고서: 4)
    revenue          = Column(BigInteger, nullable=True)    # 매출액
    operating_income = Column(BigInteger, nullable=True)    # 영업이익
    net_income       = Column(BigInteger, nullable=True)    # 당기순이익
    total_assets     = Column(BigInteger, nullable=True)    # 자산총계
    created_at       = Column(DateTime(timezone=False), server_default=KST_NOW, nullable=False)

    __table_args__ = (UniqueConstraint("corp_code", "year", "quarter", name="uq_financial_statement"),)
```

### ReportChunk — 사업보고서 청크 (RAG 소스)

```python
class ReportChunk(Base):
    __tablename__ = "report_chunks"

    id          = Column(Integer, primary_key=True)
    corp_code   = Column(String(20), nullable=False)
    corp_name   = Column(String(200), nullable=False)
    report_year = Column(Integer, nullable=False)
    rcept_no    = Column(String(20), nullable=False)    # DART 접수번호 (원천 추적)
    chunk_type  = Column(String(50), nullable=False)    # "business_summary" | "director_analysis" | "audit_opinion"
    subsection  = Column(String(500), nullable=False, default="")  # 소제목 (없으면 "")
    content     = Column(Text, nullable=False)           # 청킹된 텍스트 (RAG 검색 대상)
    embedding   = Column(Vector(768), nullable=True)    # pgvector — RAG 유사도 검색
    created_at  = Column(DateTime(timezone=False), server_default=KST_NOW, nullable=False)

    __table_args__ = (
        UniqueConstraint("corp_code", "report_year", "chunk_type", "subsection",
                         name="uq_report_chunk"),
    )
```

---

### CompanyEntity — 기업 엔티티 사전 (Entity Linking용)

뉴스 본문에서 기업명을 추출해 ticker에 매핑(Entity Linking)할 때 사용하는 기준 테이블이다.  
06 뉴스 분석 기획서의 `company_tags` 추출 단계에서 이 테이블을 조회한다.

**필요 배경**: "삼성전자 / Samsung Electronics / 삼전 / SSNLF" 같은 이름 변형이 모두 같은 기업임을 LLM이 알아야 한다. 변형 목록 없이 LLM에 의존하면 오매핑이 발생하므로 서비스 차원의 엔티티 사전으로 관리한다.

```python
from sqlalchemy import ARRAY, ForeignKey, Text, text

class CompanyEntity(Base):
    __tablename__ = "company_entities"

    id          = Column(Integer, primary_key=True)
    stock_code  = Column(String(20), nullable=False, unique=True)  # 종목 코드 (예: "005930")
    name_ko     = Column(String(200), nullable=False)               # 공식 한국어명 (예: "삼성전자")
    name_en     = Column(String(200), nullable=True)                # 영문명 (예: "Samsung Electronics")
    aliases     = Column(ARRAY(Text), nullable=False, server_default=text("'{}'::text[]"))  # 별칭 목록
    corp_code   = Column(String(20), nullable=True)                 # DART 기업 고유코드
    market      = Column(String(10), nullable=False)                # "KOSPI" | "KOSDAQ"
    sector_id   = Column(Integer, ForeignKey("sectors.id"), nullable=True)  # 섹터 (sectors 테이블 FK)
    is_active   = Column(Boolean, server_default=text("true"), nullable=False)  # False=수집 비활성화
    created_at  = Column(DateTime(timezone=False), server_default=KST_NOW, nullable=False)
    updated_at  = Column(DateTime(timezone=False), onupdate=KST_NOW, nullable=True)
```

> **수집 유니버스 겸 Entity 사전**: `company_entities`는 Entity Linking 기준일 뿐 아니라 **수집 대상 종목 목록**이기도 하다. 수집기들은 [`tools/company_loader.load_active_companies()`](../../services/collector/tools/company_loader.py)로 `is_active=True`인 기업만 로드한다. 종목 유니버스 자체는 [`company_master_collector`](../../services/collector/company_master_collector.py)가 DART corpCode.xml + PyKRX로 동기화한다(§7.5).

**aliases 관리 원칙:**

| 별칭 유형 | 예시 | 포함 기준 |
|---------|------|---------|
| 축약어 | 삼전, 하닉 | 실제 언론 기사에서 자주 쓰이는 것만 |
| 영문 축약 ticker | SSNLF, HXSCL | 해외 기사 수집 시 매핑 필요 |
| 과거 사명 | — | M&A·사명 변경 시 추가 |
| 우선주·ETF | 삼성전자우 | stock_code가 다르므로 primary가 아닌 alias로 등록 |

신규 종목은 `company_master_collector`가 `is_active=False`로 삽입해 기존 추적 종목에 영향을 주지 않으며, 추적 대상은 운영자가 `is_active=True`로 승격한다. (`sector_id` 매핑·`aliases`는 seed/수동 관리)

---

## 7. 수집 파이프라인 아키텍처

### 7.1 전체 파이프라인 구조

`CompanyCollector`는 **Airflow 파이프라인이 실행하는** 단계 컴포넌트 중 하나다.  
전체 구조는 뉴스 기획서 섹션 10.1을 참고한다.

```
Airflow DAG (각 Task가 단계를 직접 호출)
  ├── NewsCollector      ← 뉴스 수집
  ├── CompanyCollector   ← 기업 데이터 수집 (이 문서)
  ├── Preprocessor       ← 전처리 (별도 단계, → 04)
  └── EmbeddingClusterer ← 임베딩·클러스터링
```

단계 간 직접 통신은 없다. **공유 DB를 통해 데이터를 전달**한다.

---

### 7.2 실행 타이밍 (Airflow DAG)

| 시점 | 실행 단계 | 내용 |
|------|------------|------|
| **09:00** | NewsCollector + CompanyCollector (병렬) | 전일 야간 공시 수집 (메타데이터) |
| **15:30** | NewsCollector + CompanyCollector (병렬) | 당일 공시 수집 (메타데이터) |
| **월별** | CompanyCollector | 거시지표(금리·CPI·M2, ECOS) |
| **분기 1회** | CompanyCollector | 재무제표·사업보고서 텍스트 |
| **주기 동기화** | company_master_collector | 종목 유니버스(DART corpCode + PyKRX) |

> 주가·환율은 적재 DAG에 포함하지 않는다(on-demand 조회). 기존 16:30 "주가·환율 장 마감 수집" 슬롯은 제거되었다.

```python
# dags/jangdokdae_macro.py — 월별 거시지표 수집 DAG (Task가 단계 직접 호출)
def collect_macro_task(**ctx):
    asyncio.run(CompanyCollector().run("macro"))   # ECOS 거시지표 (전처리·임베딩 불필요)
```

---

### 7.3 CompanyCollector 구조

전체 디렉토리 구조는 [01 §7](./01-pipeline-orchestration-design.md#7-디렉토리-구조)을 단일 출처로 한다. 기업 수집이 닿는 파일 (✅ 구현 / ⏳ 예정):

```
services/
  ├── pipeline/company_collector.py    ⏳ 단계 진입점 (Airflow Task — 정적 분기)
  └── collector/
      ├── tools/
      │     ├── save_tool.py           ✅ 테이블별 UPSERT 경계
      │     ├── company_loader.py      ✅ is_active 기업 로드
      │     └── redact.py              ✅ 로그 API 키 마스킹
      ├── dart_collector.py            ✅ 공시 메타데이터 (list.json)
      ├── financial_collector.py       ✅ 재무제표 (fnlttSinglAcntAll.json)
      ├── report_collector.py          ✅ 사업보고서 텍스트 (document.xml → 청킹)
      ├── stock_collector.py           ✅ 주가 (FinanceDataReader, on-demand)
      ├── macro_collector.py           ✅ 환율(on-demand) + ECOS 거시지표(적재)
      ├── company_master_collector.py  ✅ 종목 유니버스 동기화 (corpCode + PyKRX)
      └── stock_symbols.py             ✅ StockSymbol 값 객체 (DB 폴백 fixture)

scripts/                               ⏳ 최초 1회 수동 실행 (Backfill, 적재 대상만)
  └── backfill_market_indicators.py · backfill_disclosures.py
```

> 적재 진입점(`services/pipeline/company_collector.py`)·DAG(`dags/`)·backfill 스크립트(`scripts/`)는 아직 미구현이다. 현재는 수집기 모듈(`services/collector/*`)과 저장 도구(`save_tool`)까지 구현되어 있다. 주가 backfill 스크립트는 on-demand 전환으로 제거되었다.

---

### 7.4 CompanyCollector 흐름

`schedule` 파라미터에 따라 수집 대상을 분기한다.

```
CompanyCollector.run(schedule)
        │
        ├─ schedule="morning" | "afternoon"
        │       ▼
        │   [dart_collect 노드]
        │     DARTCollector.collect(bgn_de, end_de)
        │     → 신규 공시 메타데이터 → disclosures (content=NULL, is_analyzed=False)
        │     → 주요 공시 발생 시 분석 파이프라인 즉시 트리거 (본문은 그때 fetch)
        │
        ├─ schedule="macro"   (월별)
        │       ▼
        │   [macro_collect 노드]
        │     MacroCollector.collect_ecos(bgn_ym, end_ym) → market_indicators (금리·CPI·M2)
        │     (환율 collect()는 적재 아님 — 분석 시점 on-demand 조회용)
        │
        └─ schedule="quarterly"
                ▼
            [financial_collect 노드]  ← asyncio.gather 병렬
              FinancialCollector.collect()  → financial_statements
              ReportCollector.collect()     → report_chunks (embedding=NULL)
              → EmbeddingClusterer 트리거 (사업보고서 임베딩)
```

> 주가는 어느 schedule에도 적재 노드가 없다. `StockCollector`는 분석 단계에서 on-demand 조회 함수로만 호출된다.

---

### 7.5 각 모듈 책임

**`DARTCollector`** ✅
- DART `list.json`으로 공시 메타데이터 조회 (`pblntf_ty=A`, `pblntf_ty=B`)
- (기업 × 공시유형) 단위 병렬 + 에러 격리, `total_page` 페이지네이션
- 신규 공시는 `content=NULL`·`is_analyzed=False`로 저장. 본문은 분석 단계 fetch

**`FinancialCollector`** ✅
- DART `fnlttSinglAcntAll.json`으로 분기별 핵심 재무 4계정 수집 → `FinancialStatement`
- 연결(CFS) 우선·개별(OFS) 폴백, 손익은 `IS`/`CIS` 둘 다 허용

**`ReportCollector`** ✅ (재무와 분리된 별도 모듈)
- DART `document.xml`(ZIP)로 사업보고서 본문 다운로드 → `parse_report_sections()`로 섹션 청킹 → `ReportChunk` (embedding=NULL)
- 정정 공시 대비 `rcept_dt` 최신본 선택

**`StockCollector`** ✅ (on-demand)
- FinanceDataReader로 국내 일봉(OHLCV) 조회 — 적재 아님, 분석 시점 호출
- 시총·외국인 보유(pykrx), 해외 주가(yfinance)는 미구현(Phase 2)

**`MacroCollector`** ✅
- `collect()`: FinanceDataReader 환율(USD/JPY/EUR/CNY) — **on-demand 조회**
- `collect_ecos()`: 한국은행 ECOS API로 금리·CPI·M2 수집 — **적재**

**`company_master_collector`** ✅
- DART corpCode.xml(전체 상장사) + PyKRX(섹터·마켓)로 `company_entities` 동기화
- 기존 레코드는 `market`·`corp_code`만 갱신(추적 종목의 `is_active`·`name_ko` 보존), 신규는 `is_active=False`로 삽입

---

### 7.6 Backfill 전략

`scripts/`는 최초 1회만 수동 실행한다. 주기 실행 DAG와 분리해 실수로 재실행하는 것을 방지한다. **적재 대상만 backfill하며, on-demand인 주가·환율은 대상이 아니다.**

| 스크립트 | 수집 범위 | 예상 소요 시간 |
|---------|---------|-------------|
| `backfill_market_indicators.py` | 금리·CPI·M2 5년치 (ECOS) | 약 5분 |
| `backfill_disclosures.py` | 주요 종목 공시·재무·사업보고서 N년치 | 약 30분 |


## 8. 에러 처리 전략

단계(파이프라인) 수준의 에러 처리는 [`01-pipeline-orchestration-design.md` 9장 에러 처리](./01-pipeline-orchestration-design.md)을 따른다.  
기업 데이터 수집에서 추가로 고려할 항목은 다음과 같다.

| 시나리오 | 처리 방식 |
|---------|---------|
| DART API 응답 없음 | exponential backoff 3회 재시도 (1s → 2s → 4s), 이후 ERROR 로그 |
| DART 공시 본문 파싱 실패 | 메타데이터만 저장 (`content=NULL`) — 본문은 분석 단계 fetch이므로 수집은 영향 없음 |
| FinanceDataReader 조회 실패 (on-demand) | 종목 단위 에러 격리 후 스킵 → 해당 분석은 주가 컨텍스트 없이 진행, 캐시 만료 후 재시도 |
| yfinance rate limit 초과 (Phase 2) | `requests-cache` 활용, 요청 간격 1초 이상 유지 |
| ECOS API 월별 데이터 중복 | `ON CONFLICT DO NOTHING` UPSERT로 처리 (currency NULL은 `NULLS NOT DISTINCT`) |
| DART 재무 API(CFS) 데이터 없음 | 개별재무제표(OFS)로 폴백, 둘 다 없으면 해당 기업·분기 스킵 |
| 사업보고서 ZIP/XML 파싱 실패 | 해당 기업 스킵(에러 격리), 다른 기업 정상 수집 |
| Backfill 중 중단 | 스크립트 재실행 시 `ON CONFLICT DO NOTHING`으로 안전하게 재개 |

---

## 9. API 키 목록

| API | 발급처 | 비용 | 소요 시간 | 환경 변수명 |
|-----|--------|------|----------|------------|
| **DART** | [opendart.fss.or.kr](https://opendart.fss.or.kr) | 무료 | 즉시 | `DART_API_KEY` |
| **한국은행 ECOS** | [ecos.bok.or.kr](https://ecos.bok.or.kr/api/) | 무료 | 즉시 | `ECOS_API_KEY` |

**API 키 불필요 (pip install만으로 사용 가능):**

| 라이브러리 | 설치 명령 | 용도 | 상태 |
|-----------|----------|------|------|
| FinanceDataReader | `uv add finance-datareader` | 국내 주가·환율 (on-demand) | ✅ |
| pykrx | `uv add pykrx` | 종목 섹터·마켓 동기화 / 시총·외국인(Phase 2) | ✅ |
| yfinance | `uv add yfinance` | 해외 대형주 주가·재무제표 | ⏳ Phase 2 |

> **dart-fss 미사용**: 재무제표는 DART `fnlttSinglAcntAll.json`(구조화 JSON)을 httpx로 직접 호출하므로 `dart-fss` 라이브러리는 추가하지 않는다(§4.2).

---

## 10. 구현 로드맵

단계별로 독립 구현 후 **Airflow DAG**로 통합한다.  
Airflow 통합은 뉴스 기획서 Phase 4와 동일하게 진행한다.

### Phase 1 — 수집기 도구 구현 ✅ (구현 완료)

| 단계 | 내용 | 산출물 | 상태 |
|------|------|--------|------|
| 1 | DART API 키, ECOS API 키 발급 + `.env` 등록 | `.env` | ✅ |
| 2 | `DARTCollector` 구현 (공시 메타데이터, `list.json`) | `services/collector/dart_collector.py` | ✅ |
| 3 | `FinancialCollector` 구현 (`fnlttSinglAcntAll.json`) | `services/collector/financial_collector.py` | ✅ |
| 4 | `ReportCollector` 구현 (`document.xml` + 청킹) | `services/collector/report_collector.py` | ✅ |
| 5 | `StockCollector`(on-demand) · `MacroCollector`(환율 on-demand + ECOS 적재) | `services/collector/stock_collector.py`, `macro_collector.py` | ✅ |
| 6 | `company_master_collector` (유니버스 동기화) + `company_loader` | `services/collector/` | ✅ |
| 7 | `save_tool` (테이블별 UPSERT 경계) | `services/collector/tools/save_tool.py` | ✅ |
| 8 | DB 스키마 적용 (6개 ORM 모델) | `app/db/orm_models/` | ✅ |

### Phase 2 — CompanyCollector 적재 진입점 ⏳

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 9 | `CompanyCollector` 정의 (schedule 분기: dart / macro / quarterly) | `services/pipeline/company_collector.py` |
| 10 | Airflow DAG 작성 (공시 daily, 거시 월별, 재무·사업보고서 quarterly) | `dags/` |
| 11 | Backfill 스크립트 (거시지표·공시·재무·사업보고서) | `scripts/backfill_*.py` |

### Phase 3 — 사업보고서 RAG ⏳

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 12 | Neon pgvector 활성화 | DB 마이그레이션 |
| 13 | `ReportEmbedder` 구현 (Vertex AI → pgvector) | `services/embedder/report_embedder.py` |
| 14 | LangChain PGVector RAG 검색 + 주가·환율 on-demand 조회 연동 | `app/llm/rag.py` |

### Phase 4 — 확장 ⏳

| 단계 | 내용 |
|------|------|
| 15 | 전체 종목(코스피+코스닥)으로 추적 유니버스 확장 (`is_active` 승격) |
| 16 | 주가 적재 전환 검토 (전종목 추세 분석 시) + pykrx 시총·외국인, yfinance 해외 주가 |
| 17 | 공시 실시간 감시 (30분 간격 interval job) |
