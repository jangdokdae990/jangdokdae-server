# 기업 데이터 수집 기획서

**작성일** 2026-05-28  
**기획 범위** 기업 데이터 수집 → DB 적재 → RAG 소스 준비  
**관련 문서**  
- [에이전트 오케스트레이션 아키텍처](./01-agent-orchestration-design.md)
- [임베딩·클러스터링 기획서](./05-embedding-clustering-design.md)

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
  공시(DART)
  사업보고서(dart-fss)   →  DB 적재  →  임베딩(pgvector)  →  ImpactAnalysisChain
  주가(FinanceDataReader + pykrx + yfinance)                    (related_companies)
  환율·거시지표(ECOS)
```

### 1.2 기업 데이터 종류와 용도 요약

| 데이터 | 출처 | 주요 용도 |
|--------|------|----------|
| 공시 | DART REST API | 분석 파이프라인 input + RAG 소스 |
| 사업보고서 재무제표 | dart-fss | RAG 소스 (재무 수치 구조화) |
| 사업보고서 텍스트 | dart-fss | RAG 소스 (사업 내용·위험 요소 청킹) |
| 주가 | FinanceDataReader | 분석 보조 컨텍스트 |
| 주가 (해외) | yfinance | 분석 보조 컨텍스트 (대형주) |
| 환율 | FinanceDataReader | 거시 이슈 분석 컨텍스트 |
| 거시지표 (금리·CPI) | 한국은행 ECOS API | 거시 이슈 분석 컨텍스트 |

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

| 분류 | 세부 항목 | 출처 | 수집 주기 | 분석 파이프라인 역할 |
|------|----------|------|----------|---------------------|
| **공시** | 전자공시, 주요사항 | DART REST API | 이벤트 발생 시 | input + RAG 소스 |
| **사업보고서** | 재무제표, 사업 현황 | dart-fss | 분기 1회 | **RAG 소스 핵심** |
| **주가 (국내)** | 일봉, 시총, 외국인 보유 | FinanceDataReader + pykrx | 매 거래일 | 분석 보조 컨텍스트 |
| **주가 (해외)** | 일봉, 재무제표 | yfinance | 매 거래일 | 분석 보조 컨텍스트 |
| **환율** | USD/KRW, JPY/KRW 등 | FinanceDataReader | 매 거래일 | 거시 이슈 분석 컨텍스트 |
| **거시지표** | 기준금리, CPI, M2 | 한국은행 ECOS | 월별 | 거시 이슈 분석 컨텍스트 |

---

## 4. API별 상세

### 4.1 DART REST API — 공시 수집

- **URL**: [opendart.fss.or.kr](https://opendart.fss.or.kr)
- **비용**: 완전 무료, API 키 즉시 발급
- **용도**: 공시 목록 수집, 공시 원문 텍스트 저장

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

### 4.2 dart-fss — 사업보고서 재무제표

**dart-fss를 선택한 이유**: DART REST API로 사업보고서 본문을 직접 파싱하면 HTML 처리가 복잡하다. `dart-fss` 라이브러리가 재무제표 자동 파싱을 해준다.

| 항목 | DART REST API 직접 사용 | dart-fss 사용 |
|------|------------------------|--------------|
| 재무제표 파싱 | HTML 직접 파싱 필요 (복잡) | DataFrame 자동 반환 |
| 코드 복잡도 | 높음 | 낮음 |
| 공시 목록 조회 | 가능 | 가능 |
| 유지보수 | 파싱 로직 직접 관리 | 라이브러리 업데이트 의존 |
| **결론** | 공시 목록·원문에 사용 | **재무제표 파싱에 사용** |

```bash
uv add dart-fss
```

#### 코드 예시

```python
import dart_fss as fss
from app.core.config import settings

fss.set_api_key(settings.DART_API_KEY)

def fetch_financial_statements(corp_name: str, start_date: str = "20230101") -> dict:
    """기업의 연결재무제표 추출"""
    corp_list = fss.get_corp_list()
    corps = corp_list.find_by_name(corp_name)
    if not corps:
        raise ValueError(f"기업을 찾을 수 없습니다: {corp_name}")

    corp = corps[0]
    # 연결재무제표 자동 파싱 (매출, 영업이익, 부채비율 등 DataFrame 반환)
    fs = corp.extract_fs(bgn_de=start_date)

    return {
        "revenue": fs["is"].loc["매출액"].iloc[-1],           # 최근 연도 매출액
        "operating_income": fs["is"].loc["영업이익"].iloc[-1], # 최근 연도 영업이익
        "net_income": fs["is"].loc["당기순이익"].iloc[-1],     # 최근 연도 당기순이익
        "total_assets": fs["bs"].loc["자산총계"].iloc[-1],     # 최근 연도 자산총계
    }
```

**DART REST API + dart-fss 역할 분담:**

```
DART REST API  →  공시 목록 수집, 공시 원문 텍스트 저장
dart-fss       →  사업보고서 재무제표 파싱 (구조화 저장)
```

---

### 4.3 주가 데이터 — FinanceDataReader + pykrx + yfinance

실무에서 가장 많이 쓰이는 조합이다. 세 라이브러리가 서로 보완 관계다.

#### 역할 분담

| 라이브러리 | 용도 | 이유 |
|-----------|------|------|
| **FinanceDataReader** | 국내+해외 주가, 환율, 지수 (기본) | 단일 인터페이스로 통합, 코드 단순 |
| **pykrx** | 국내 시총, 외국인 보유 (보조) | KRX 공식 데이터, FinanceDataReader 미제공 상세 데이터 |
| **yfinance** | 해외 대형주 주가·재무제표 | Yahoo Finance 기반, 손익계산서·대차대조표 제공 |

#### 코드 예시

```python
import FinanceDataReader as fdr
from pykrx import stock as pykrx_stock
import yfinance as yf

# ─── 국내 주가 ───────────────────────────────────────────
# FinanceDataReader — 일봉 기본 수집
df_kr = fdr.DataReader("005930", "2024-01-01")    # 삼성전자

# pykrx — 시가총액·외국인 보유 (상세)
market_cap = pykrx_stock.get_market_cap("20240101", "20240131", "005930")

# ─── 해외 주가·재무제표 ───────────────────────────────────
# yfinance — 일봉
ticker = yf.Ticker("AAPL")
df_us = ticker.history(start="2024-01-01")

# yfinance — 재무제표 (연간/분기)
income_stmt = ticker.income_stmt          # 손익계산서
balance_sheet = ticker.balance_sheet     # 대차대조표
cash_flow = ticker.cashflow              # 현금흐름표

# ─── DB 적재 ──────────────────────────────────────────────
async def save_stock_price(symbol: str, df, region: str) -> None:
    for date, row in df.iterrows():
        stmt = insert(StockPrice).values(
            symbol=symbol,
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=int(row["Volume"]),
            region=region,        # "domestic" | "global"
            date=date.date(),
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "date"])
        await db.execute(stmt)
```

> **yfinance 주의사항**: 비공식 API로 rate limit이 있다. `requests-cache`와 함께 사용하고, 대량 수집 시 요청 간격을 둬야 한다. 한국 소형주 커버리지 부족 → 국내 주가는 FinanceDataReader / pykrx 우선.

---

### 4.4 환율 — FinanceDataReader

주가·지수와 같은 라이브러리로 환율도 처리한다. 별도 환율 API를 추가하지 않는다.

```python
import FinanceDataReader as fdr

def fetch_exchange_rates(start_date: str) -> dict:
    return {
        "USD": fdr.DataReader("USD/KRW", start_date),
        "JPY": fdr.DataReader("JPY/KRW", start_date),
        "EUR": fdr.DataReader("EUR/KRW", start_date),
        "CNY": fdr.DataReader("CNY/KRW", start_date),
    }
```

**선택 이유**: 실무에서 별도 환율 API를 추가하는 사례가 거의 없다. FinanceDataReader가 환율·주가·지수를 통합 제공하므로 수집기 코드를 하나로 유지한다.

---

### 4.5 거시지표 — 한국은행 ECOS API

- **URL**: [ecos.bok.or.kr/api](https://ecos.bok.or.kr/api/)
- **비용**: 무료
- **이유**: FinanceDataReader는 환율·지수 위주. 기준금리·CPI·M2 같은 거시지표는 한국은행 ECOS만 제공

#### 주요 통계표 코드표

| 지표 | 통계표 코드 | 주기 | 분석 활용 |
|------|------------|------|----------|
| 기준금리 | `722Y001` | 월별 | 금리 변동 이슈 분석 |
| 소비자물가지수(CPI) | `901Y009` | 월별 | 인플레이션 이슈 분석 |
| 원/달러 환율 | `731Y003` | 일별 | 환율 이슈 분석 |
| 코스피 지수 | `802Y001` | 일별 | 시장 전체 흐름 |
| M2 통화량 | `101Y004` | 월별 | 유동성 분석 |

#### 코드 예시

```python
import httpx

ECOS_BASE_URL = "https://ecos.bok.or.kr/api"

async def fetch_ecos_indicator(
    stat_code: str,
    item_code: str,
    start_date: str,
    end_date: str,
    period_type: str = "MM",  # "DD" | "MM" | "QQ" | "YY"
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
    period_type="MM",
)
```

---

## 5. DB 적재 방법론

### 5.1 데이터 유형별 전략

| 유형 | 패턴 | 크기 | 적재 전략 |
|------|------|------|----------|
| **주가** | 매 거래일 | 작음 (숫자) | Append-only, `(symbol, date)` UPSERT |
| **환율·거시지표** | 매 영업일/월별 | 작음 | Append-only, `(indicator_type, currency, date)` UPSERT |
| **공시** | 이벤트 발생 시 | 중간 (텍스트) | Append-only, `rcept_no` unique |
| **사업보고서** | 분기 1회 | **매우 큼** | **청킹 필수**, 섹션 단위 분할 후 임베딩 |

**시계열 데이터 (주가·환율·거시지표)**:
- Append-only 패턴. 기존 행 수정 없음
- 중복은 UPSERT `ON CONFLICT DO NOTHING`으로 처리
- 재실행해도 안전 (멱등성 보장)

**이벤트 데이터 (공시)**:
- DART 접수번호(`rcept_no`)가 고유 식별자
- 같은 공시를 두 번 수집해도 `rcept_no` unique로 자동 차단

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

### 5.3 Backfill vs Incremental 분리 이유

서비스 시작 시 과거 데이터가 없으면 LLM이 "최근 흐름"을 참고할 수 없다.

```
scripts/                             ← 최초 1회만 실행 (Backfill)
  ├── backfill_stock_prices.py        # 과거 1~3년치 주가 일괄 적재
  ├── backfill_market_indicators.py   # 과거 5년치 금리·환율·CPI
  └── backfill_disclosures.py         # 과거 3년치 사업보고서

tasks/                               ← 매일 자동 실행 (Incremental)
  └── collect_market_data.py          # 당일 데이터만 추가 (16:30, 장 마감 후)
```

**분리 이유**: 한 번 실행하는 코드와 매일 실행하는 코드가 섞이면 실수로 재실행 시 데이터 중복·오염 위험이 있다. `scripts/`는 명시적으로 수동 실행해야 하는 코드임을 디렉토리 위치로 표현한다.

### 5.4 사업보고서 청킹 전략

사업보고서 원문은 수십~수백 페이지다. 그대로 하나의 TEXT 컬럼에 저장하면 LLM 컨텍스트 한도를 초과한다.

**방법 A — 섹션 단위 청킹 (RAG 소스용)**

| chunk_type | 설명 | RAG 검색 쿼리 예시 |
|------------|------|------------------|
| `business_summary` | 사업 개요, 주요 제품 | "삼성전자 주요 사업" |
| `risk_factors` | 사업 위험 요소 | "삼성전자 리스크" |
| `financial_summary` | 재무 요약 (텍스트 형태) | "삼성전자 재무 현황" |

```python
# 섹션별 청킹 예시
sections = {
    "business_summary": report_text[start_idx:business_end],
    "risk_factors": report_text[risk_start:risk_end],
    "financial_summary": report_text[fin_start:fin_end],
}

for chunk_type, content in sections.items():
    chunk = ReportChunk(
        corp_code=corp_code,
        corp_name=corp_name,
        report_year=year,
        chunk_type=chunk_type,
        content=content,
        # embedding은 services/embedder에서 별도 생성
    )
    db.add(chunk)
```

**방법 B — 재무 수치 구조화 저장 (dart-fss 활용)**

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

**두 방법 병행**: 재무 수치는 `FinancialStatement` 구조화 테이블, 텍스트(사업 내용·위험 요소)는 `ReportChunk` 청킹 후 임베딩 저장.

### 5.5 UPSERT 중복 방지 전략

모든 적재는 `ON CONFLICT DO NOTHING`으로 upsert → 재실행해도 안전 (멱등성).

```python
# 주가: (symbol, date) 복합 유니크
__table_args__ = (UniqueConstraint("symbol", "date"),)

# 공시: DART 접수번호 유니크
rcept_no = Column(String(20), unique=True)

# 거시지표: (indicator_type, currency, date) 복합 유니크
__table_args__ = (UniqueConstraint("indicator_type", "currency", "date"),)

# UPSERT 실행 패턴
from sqlalchemy.dialects.postgresql import insert

async def upsert_stock_price(session, data: dict) -> None:
    stmt = insert(StockPrice).values(**data)
    stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "date"])
    await session.execute(stmt)
    await session.commit()
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
    is_analyzed      = Column(Boolean, default=False)                   # 분석 파이프라인 처리 여부
    disclosed_at     = Column(DateTime, nullable=False)
    created_at       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    embedding        = Column(Vector(768), nullable=True)               # pgvector — 유사도 검색
```

### StockPrice — 주가 시계열

```python
from sqlalchemy import Column, Integer, String, Float, BigInteger, Date, DateTime, UniqueConstraint

class StockPrice(Base):
    __tablename__ = "stock_prices"

    id         = Column(Integer, primary_key=True)
    symbol     = Column(String(20), nullable=False)      # 종목 코드 (예: "005930")
    name       = Column(String(100), nullable=False)     # 종목명 (예: "삼성전자")
    open       = Column(Float, nullable=False)
    high       = Column(Float, nullable=False)
    low        = Column(Float, nullable=False)
    close      = Column(Float, nullable=False)
    volume     = Column(BigInteger, nullable=False)
    market_cap = Column(BigInteger, nullable=True)       # 시가총액 (pykrx로 보완 가능)
    date       = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("symbol", "date"),)
```

### MarketIndicator — 환율·금리·거시지표

```python
class MarketIndicator(Base):
    __tablename__ = "market_indicators"

    id             = Column(Integer, primary_key=True)
    indicator_type = Column(String(50), nullable=False)   # "exchange_rate" | "interest_rate" | "cpi" | "kospi" | "m2"
    currency       = Column(String(10), nullable=True)    # 환율: "USD" | "JPY", 그 외 None
    value          = Column(Float, nullable=False)
    date           = Column(Date, nullable=False)
    created_at     = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("indicator_type", "currency", "date"),)
```

### FinancialStatement — 재무제표 (dart-fss)

```python
class FinancialStatement(Base):
    __tablename__ = "financial_statements"

    id               = Column(Integer, primary_key=True)
    corp_code        = Column(String(20), nullable=False)
    corp_name        = Column(String(200), nullable=False)
    year             = Column(Integer, nullable=False)
    quarter          = Column(Integer, nullable=False)      # 1~4 (연간: 4)
    revenue          = Column(BigInteger, nullable=True)    # 매출액
    operating_income = Column(BigInteger, nullable=True)    # 영업이익
    net_income       = Column(BigInteger, nullable=True)    # 당기순이익
    total_assets     = Column(BigInteger, nullable=True)    # 자산총계
    created_at       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    __table_args__ = (UniqueConstraint("corp_code", "year", "quarter"),)
```

### ReportChunk — 사업보고서 청크 (RAG 소스)

```python
class ReportChunk(Base):
    __tablename__ = "report_chunks"

    id          = Column(Integer, primary_key=True)
    corp_code   = Column(String(20), nullable=False)
    corp_name   = Column(String(200), nullable=False)
    report_year = Column(Integer, nullable=False)
    chunk_type  = Column(String(50), nullable=False)    # "business_summary" | "risk_factors" | "financial_summary"
    content     = Column(Text, nullable=False)           # 청킹된 텍스트 (RAG 검색 대상)
    embedding   = Column(Vector(768), nullable=True)    # pgvector — RAG 유사도 검색
    created_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

---

### CompanyEntity — 기업 엔티티 사전 (Entity Linking용)

뉴스 본문에서 기업명을 추출해 ticker에 매핑(Entity Linking)할 때 사용하는 기준 테이블이다.  
06 뉴스 분석 기획서의 `company_tags` 추출 단계에서 이 테이블을 조회한다.

**필요 배경**: "삼성전자 / Samsung Electronics / 삼전 / SSNLF" 같은 이름 변형이 모두 같은 기업임을 LLM이 알아야 한다. 변형 목록 없이 LLM에 의존하면 오매핑이 발생하므로 서비스 차원의 엔티티 사전으로 관리한다.

```python
from sqlalchemy.dialects.postgresql import ARRAY

class CompanyEntity(Base):
    __tablename__ = "company_entities"

    id          = Column(Integer, primary_key=True)
    symbol      = Column(String(20), nullable=False, unique=True)  # 종목 코드 (예: "005930")
    name_ko     = Column(String(200), nullable=False)               # 공식 한국어명 (예: "삼성전자")
    name_en     = Column(String(200), nullable=True)                # 영문명 (예: "Samsung Electronics")
    aliases     = Column(ARRAY(String), nullable=False, default=[]) # 별칭 목록 (예: ["삼전", "SSNLF", "삼성전자우"])
    corp_code   = Column(String(20), nullable=True)                 # DART 기업 고유코드
    market      = Column(String(10), nullable=False)                # "KOSPI" | "KOSDAQ" | "NYSE" | "NASDAQ"
    sector      = Column(String(50), nullable=True)                 # 섹터 (예: "반도체")
    updated_at  = Column(DateTime(timezone=True), nullable=True)
    created_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

**aliases 관리 원칙:**

| 별칭 유형 | 예시 | 포함 기준 |
|---------|------|---------|
| 축약어 | 삼전, 하닉 | 실제 언론 기사에서 자주 쓰이는 것만 |
| 영문 축약 ticker | SSNLF, HXSCL | 해외 기사 수집 시 매핑 필요 |
| 과거 사명 | — | M&A·사명 변경 시 추가 |
| 우선주·ETF | 삼성전자우 | symbol이 다르므로 primary가 아닌 alias로 등록 |

초기 구축은 수동으로 하고 (`data/company_entities.csv` → 초기 마이그레이션), 이후 DART corp_list와 주기적으로 동기화한다.

---

## 7. 수집 파이프라인 아키텍처

### 7.1 전체 멀티 에이전트 구조

`CompanyCollectionAgent`는 `MasterOrchestrator`가 관리하는 4개 에이전트 중 하나다.  
전체 구조는 뉴스 기획서 섹션 10.1을 참고한다.

```
MasterOrchestrator
  ├── NewsCollectionAgent      ← 뉴스 수집
  ├── CompanyCollectionAgent   ← 기업 데이터 수집 (이 문서)
  │   [전처리 — 수집 인라인 실행]
  └── EmbeddingClusteringAgent ← 임베딩·클러스터링
```

에이전트 간 직접 통신은 없다. **공유 DB를 통해 데이터를 전달**한다.

---

### 7.2 MasterOrchestrator 실행 타이밍

| 시점 | 실행 에이전트 | 내용 |
|------|------------|------|
| **09:00** | NewsAgent + CompanyAgent (병렬) | 전일 야간 공시 수집 |
| **15:30** | NewsAgent + CompanyAgent (병렬) | 당일 공시 수집 |
| **16:30** | CompanyAgent | 주가·환율·거시지표 (장 마감 후) |
| **분기 1회** | CompanyAgent | 사업보고서·재무제표 |

```python
# master_orchestrator.py 에서 CompanyCollectionAgent 호출
async def run_market_close(self) -> None:
    """16:30 — 주가·거시지표 수집"""
    await self.company_agent.run("market_close")
    # 주가·거시지표는 전처리·임베딩 불필요
```

---

### 7.3 CompanyCollectionAgent 구조

```
services/
  ├── master_orchestrator.py              ← MasterOrchestrator
  │
  ├── agents/
  │   └── company_collection_agent.py     ← CompanyCollectionAgent (LangGraph)
  │
  └── collector/
      ├── tools/
      │   ├── dart_tool.py     ← DART 공시 수집
      │   ├── stock_tool.py    ← 주가 수집 (FinanceDataReader)
      │   ├── macro_tool.py    ← 환율·금리 수집
      │   └── save_tool.py     ← DB UPSERT (뉴스 에이전트와 공유)
      ├── dart_collector.py
      ├── financial_collector.py
      ├── stock_collector.py
      └── macro_collector.py

scripts/                            ← 최초 1회 수동 실행 (Backfill)
  ├── backfill_stock_prices.py
  ├── backfill_market_indicators.py
  └── backfill_disclosures.py
```

---

### 7.4 CompanyCollectionAgent 흐름

`schedule` 파라미터에 따라 수집 대상을 분기한다.

```
CompanyCollectionAgent.run(schedule)
        │
        ├─ schedule="morning" | "afternoon"
        │       ▼
        │   [dart_collect 노드]
        │     dart_tool.collect_recent(hours=N)
        │     → 신규 공시 → disclosures 테이블 (is_analyzed=False)
        │     → 주요 공시 발생 시 분석 파이프라인 즉시 트리거
        │
        ├─ schedule="market_close"
        │       ▼
        │   [market_collect 노드]  ← asyncio.gather 병렬
        │     stock_tool.collect_today()   → stock_prices
        │     macro_tool.collect_today()   → market_indicators (환율, 금리)
        │
        └─ schedule="quarterly"
                ▼
            [financial_collect 노드]
              financial_collector.extract_fs()   → financial_statements
              financial_collector.chunk_report() → report_chunks (embedding=NULL)
              → EmbeddingClusteringAgent 트리거 (사업보고서 임베딩)
```

---

### 7.5 각 모듈 책임

**`DARTCollector`**
- DART REST API로 공시 목록 조회 (`pblntf_ty=A`, `pblntf_ty=B`)
- 신규 공시 발생 시 `is_analyzed=False`로 저장
- 주요 공시(실적·유상증자 등)는 분석 파이프라인 즉시 트리거 연동

**`FinancialCollector`**
- dart-fss로 분기별 재무제표 파싱 → `FinancialStatement` 저장
- 사업보고서 텍스트를 섹션별로 청킹 → `ReportChunk` 저장

**`StockCollector`**
- FinanceDataReader로 관심 종목 + 코스피200 일봉 수집
- 시총·외국인 보유 필요 시 pykrx 보조

**`MacroCollector`**
- FinanceDataReader로 환율(USD/KRW 등) 수집
- 한국은행 ECOS API로 금리·CPI 수집

---

### 7.6 Backfill 전략

`scripts/`는 최초 1회만 수동 실행한다. `tasks/`와 분리해 실수로 재실행하는 것을 방지한다.

| 스크립트 | 수집 범위 | 예상 소요 시간 |
|---------|---------|-------------|
| `backfill_stock_prices.py` | 코스피200 × 3년치 일봉 | 약 10분 |
| `backfill_market_indicators.py` | 환율·금리 5년치 | 약 5분 |
| `backfill_disclosures.py` | 주요 종목 사업보고서 3년치 | 약 30분 |


## 8. 에러 처리 전략

에이전트 수준의 에러 처리는 [`01-agent-orchestration-design.md` 섹션 10](./01-agent-orchestration-design.md)을 따른다.  
기업 데이터 수집에서 추가로 고려할 항목은 다음과 같다.

| 시나리오 | 처리 방식 |
|---------|---------|
| DART API 응답 없음 | exponential backoff 3회 재시도 (1s → 2s → 4s), 이후 ERROR 로그 |
| DART 공시 본문 파싱 실패 | 메타데이터만 저장 (`content=NULL`), 파싱 실패 플래그 기록 |
| FinanceDataReader 수집 실패 | 다음 영업일 수집 시 해당 날짜를 포함해 재수집 |
| yfinance rate limit 초과 | `requests-cache` 활용, 요청 간격 1초 이상 유지 |
| ECOS API 월별 데이터 중복 | `ON CONFLICT DO NOTHING` UPSERT로 처리 |
| dart-fss 재무제표 파싱 오류 | 해당 기업·분기 스킵, 다음 분기 정상 수집 |
| Backfill 중 중단 | 스크립트 재실행 시 `ON CONFLICT DO NOTHING`으로 안전하게 재개 |

---

## 9. API 키 목록

| API | 발급처 | 비용 | 소요 시간 | 환경 변수명 |
|-----|--------|------|----------|------------|
| **DART** | [opendart.fss.or.kr](https://opendart.fss.or.kr) | 무료 | 즉시 | `DART_API_KEY` |
| **한국은행 ECOS** | [ecos.bok.or.kr](https://ecos.bok.or.kr/api/) | 무료 | 즉시 | `ECOS_API_KEY` |

**API 키 불필요 (pip install만으로 사용 가능):**

| 라이브러리 | 설치 명령 | 용도 |
|-----------|----------|------|
| FinanceDataReader | `uv add finance-datareader` | 국내+해외 주가, 환율, 지수 |
| pykrx | `uv add pykrx` | 국내 시총·외국인 보유 |
| yfinance | `uv add yfinance` | 해외 대형주 주가·재무제표 |
| dart-fss | `uv add dart-fss` | 사업보고서 재무제표 파싱 |

---

## 10. 구현 로드맵

에이전트별로 독립 구현 후 `MasterOrchestrator`로 통합한다.  
MasterOrchestrator 통합은 뉴스 기획서 Phase 4와 동일하게 진행한다.

### Phase 1 — 수집기 도구 구현

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 1 | DART API 키, ECOS API 키 발급 + `.env` 등록 | `.env` |
| 2 | `DARTCollector` 구현 (공시 목록 + 원문) | `services/collector/dart_collector.py` |
| 3 | `StockCollector` 구현 (FinanceDataReader + pykrx + yfinance) | `services/collector/stock_collector.py` |
| 4 | `MacroCollector` 구현 (FinanceDataReader 환율 + ECOS 금리·CPI) | `services/collector/macro_collector.py` |
| 5 | `dart_tool`, `stock_tool`, `macro_tool` 구현 | `services/collector/tools/` |
| 6 | DB 스키마 적용 (Disclosure, StockPrice, MarketIndicator) | `app/db/models.py` |

### Phase 2 — CompanyCollectionAgent 구현

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 7 | `CompanyAgentState` 정의 | `services/agents/company_collection_agent.py` |
| 8 | `dart_collect`, `market_collect` 노드 구현 | `services/agents/company_collection_agent.py` |
| 9 | Airflow DAG 작성 (16:30 daily, 분기 quarterly) | `dags/` |

### Phase 3 — 사업보고서 + RAG

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 10 | Neon pgvector 활성화 | DB 마이그레이션 |
| 11 | `FinancialCollector` 구현 (dart-fss + 청킹) | `services/collector/financial_collector.py` |
| 12 | `ReportEmbedder` 구현 (Vertex AI → pgvector) | `services/embedder/report_embedder.py` |
| 13 | `financial_collect` 노드 추가 (quarterly) | `services/agents/company_collection_agent.py` |
| 14 | LangChain PGVector RAG 검색 구현 | `app/llm/rag.py` |

### Phase 4 — MasterOrchestrator 통합

뉴스 기획서 Phase 4와 병행 진행.

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 15 | `MasterOrchestrator`에 CompanyCollectionAgent 등록 | `services/master_orchestrator.py` |
| 16 | Backfill 스크립트 실행 (과거 데이터 일괄 적재) | `scripts/backfill_*.py` |

### Phase 5 — 확장

| 단계 | 내용 |
|------|------|
| 17 | 전체 종목(코스피+코스닥) 주가 확장 |
| 18 | pykrx 시총·외국인 보유 데이터 추가 |
| 19 | 공시 실시간 감시 (30분 간격 interval job) |
