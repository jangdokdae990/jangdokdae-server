# 뉴스 데이터 수집 기획서

**작성일** 2026-05-28  
**기획 범위** 뉴스 수집 → 전처리 → 임베딩  
**관련 문서**  
- [에이전트 오케스트레이션 아키텍처](./01-agent-orchestration-design.md)
- [전처리 기획서](./04-preprocessing-design.md)

---

## 목차

- [1. 개요](#1-개요)
- [2. 수집 대상 정의](#2-수집-대상-정의)
- [3. 저작권 및 법적 검토](#3-저작권-및-법적-검토)
- [4. 수집 소스 검토](#4-수집-소스-검토)
- [5. 수집 방법](#5-수집-방법)
- [6. 주요 뉴스 선정 방법론](#6-주요-뉴스-선정-방법론)
- [7. 뉴스 수집 에이전트](#7-뉴스-수집-에이전트)
- [8. 데이터 명세](#8-데이터-명세)
- [9. 수집 주기](#9-수집-주기)
- [10. 시스템 아키텍처](#10-시스템-아키텍처)
- [11. 구현 로드맵](#11-구현-로드맵)
- [12. 미결 사항](#12-미결-사항)
- [참고 자료](#참고-자료)

---

## 1. 개요

### 1.1 서비스에서 뉴스 데이터의 역할

장독대는 주식 초보자(주린이)가 복잡한 시장 뉴스를 쉽게 이해할 수 있도록 LLM이 뉴스를 분석하고 쉬운 언어로 풀어주는 서비스다. 뉴스 데이터는 이 서비스의 **가장 중요한 원재료**다.

뉴스는 다음 네 가지 기능에 모두 활용된다.

| 기능 | 뉴스 데이터의 역할 |
|------|-----------------|
| 주린이용 풀이 생성 | LLM이 뉴스를 읽고 쉬운 언어로 재설명 |
| 오늘의 주요 이슈 파악 | 중요도 필터링 + 클러스터링으로 핵심 이슈 선별 |
| 관심 종목 뉴스 피드 | 사용자별 관심 종목 관련 최신 뉴스 제공 |
| Issue Docent 생성 | 유사 뉴스를 묶어 하나의 이슈로 요약 |

### 1.2 수집 목표

- **수집 범위**: 국내 주식 시장 + 해외 글로벌 시장
- **수집 방법**: 무료 공개 API만 사용
- **저장 방식**: 제목 + snippet + URL (본문 전체 저장 없음)
- **텍스트 수준**: API 제공 snippet/summary로 시작, 품질 검증 후 보완 여부 결정

### 1.3 일별 수집량 추정

수집량은 **키워드 수 × 소스 수**에 비례한다. 키워드 설계가 API 호출 비용과 임베딩 비용을 직접 결정한다.

종목 키워드는 **3티어 차등 수집**으로 운영한다 (5.2절 참조).

| 소스 | 쿼리 수 (추정) | 건당 반환 | 수집량 | 중복 제거 후 |
|------|-------------|---------|-------|------------|
| Google RSS (국내 고정 키워드) | ~35 | 10~20건 | ~500건 | ~110건 |
| Google RSS (해외 고정 키워드) | ~15 | 10~20건 | ~200건 | ~60건 |
| Naver API — Tier 1 (30종목 × 2수식어 × 2회/일) | 120 | 15건 | ~1,800건 | ~360건 |
| Naver API — Tier 2 (70종목 × 1수식어 × 1회/일) | 70 | 15건 | ~1,050건 | ~260건 |
| Finnhub (해외 종목) | ~20종목 | 10~30건 | ~400건 | ~200건 |
| **합계** | | | **~3,950건** | **~990건/일** |

> 기존 대비 API 호출 **52% 감소** (400 → 190 Naver queries), 수집량 **48% 감소** (~1,900 → ~990건/일).  
> Tier 3 종목(101번째~)은 개별 수집 없이 섹터 키워드로 간접 커버한다.

**성능 영향:**
- Vertex AI 임베딩 API: 건당 호출 → 종목 수 증가 시 비용 상승
- pgvector 클러스터링: 누적 벡터 증가 시 인덱스 없으면 선형 느려짐 → **HNSW 인덱스 필수**

---

## 2. 수집 대상 정의

### 2.1 뉴스 유형 분류

| 유형 | 설명 | 예시 |
|------|------|------|
| **시장 뉴스** | 코스피·코스닥·금리·환율 등 거시 경제 이슈 | "한국은행 기준금리 동결 결정" |
| **종목 뉴스** | 특정 기업·산업 관련 뉴스 | "삼성전자 3분기 영업이익 발표" |

### 2.2 수집 범위

```
국내
  시장 뉴스  →  코스피, 코스닥, 금리, 환율, 반도체, 2차전지 등 키워드
  종목 뉴스  →  사용자 관심 종목 기반 동적 수집

해외
  시장 뉴스  →  Fed, S&P500, NASDAQ, 유가 등 글로벌 거시 키워드
  종목 뉴스  →  관심 해외 종목 ticker 기반 수집
```

---

## 3. 저작권 및 법적 검토

### 3.1 서비스 성격 — 학습 서비스

장독대는 **주식 투자 추천·매매 신호를 제공하는 투자 서비스가 아니다.** 주린이(주식 초보자)가 뉴스와 시장 개념을 이해할 수 있도록 돕는 **주식 학습 플랫폼**이다.

이 구분은 뉴스 데이터 이용 약관 해석에 직접적인 영향을 준다.

| 구분 | 투자 서비스 | 장독대 (학습 서비스) |
|------|-----------|-------------------|
| 목적 | 매매 신호, 수익 추구 | 개념 학습, 뉴스 이해 |
| Naver API 약관 적용 | 상업적 이용 → 위반 가능 | 비상업적 학습 목적 → 허용 범위 |
| 유료화 시점 | — | 유료화·광고 수익화 시 재검토 필요 |

---

### 3.2 뉴스 저작권 기본 원칙

뉴스 기사는 저작권법상 저작물로 보호된다. 뉴스사의 기사 모음은 별도 데이터베이스권으로도 보호된다. 무단 크롤링 및 본문 복제·재배포는 저작권법 위반과 함께 컴퓨터 업무 방해죄에 해당할 수 있다.

크롤링의 합법성은 다음 기준으로 판단된다(대법원 판례 기준).

- robots.txt 준수 여부
- 서버에 과도한 부하를 주지 않을 것
- 상업적 무임승차 목적이 아닐 것
- 이용약관 위반이 없을 것

---

### 3.3 수집 방법별 리스크 등급

| 행위 | 리스크 | 근거 |
|------|--------|------|
| 공개 RSS 피드에서 제목·URL 수집 | **낮음** | 언론사가 공개 배포한 메타데이터 |
| Google News RSS로 snippet 수집 | **낮음** | 공개 API, 학습 목적 |
| Naver 뉴스 API — 무료 학습 서비스 | **낮음** | 비상업적 목적 허용 범위 |
| Naver 뉴스 API — 유료화·수익화 후 | **중간** | 유료화 시 상업적 이용 재검토 필요 |
| 뉴스 본문 전체를 DB에 저장 | **높음** | 저작물 무단 복제에 해당 |
| 언론사 웹사이트 직접 크롤링 | **높음** | robots.txt 위반, 서버 부하 유발 가능 |

---

### 3.4 채택 전략 및 근거

**제목 + snippet + URL만 저장한다. 본문 전체는 DB에 저장하지 않는다.**

- Google News RSS와 Finnhub API가 제공하는 snippet/summary는 API 이용약관 범위 내의 데이터다.
- Naver 뉴스 API는 비상업적 학습 서비스로서 이용약관 허용 범위 내에서 사용한다.
- 본문 전체가 필요한 경우 원문 URL로 연결하여 사용자가 직접 접근하도록 한다.
- 서비스 유료화·광고 수익화 시점에 Naver API 이용약관을 재검토하고, 필요 시 GNews 등 유료 API로 전환한다.

---

## 4. 수집 소스 검토

### 4.1 후보 소스 전체 비교

수집 방법을 결정하기 전에 국내외 주요 뉴스 API를 조사하였다.

| 소스 | 지역 | 본문 제공 | 무료 한도 | 상업 이용 | 검토 결과 |
|------|------|----------|----------|----------|----------|
| **Google News RSS** | 국내+해외 | snippet | 무제한 | 허용 | ✅ **채택** |
| **Naver News API** | 국내 | 짧은 발췌 | 25,000건/일 | 비상업 한정 | ✅ **채택 (MVP 단계)** |
| **Finnhub API** | 해외 | summary | 60 req/min | 허용 | ✅ **채택** |
| BigKinds API | 국내 | 200자 | 무료 → **유료 전환됨** | 비상업 | ❌ 제외 |
| DeepSearch 뉴스 API | 국내+해외 | 3줄 요약 | **무료 불가** | 가능 | ❌ 제외 |
| NewsData.io | 국내+해외 | 유료만 전체 | 200건/일 | 가능 | ❌ 비용 문제 |
| GNews | 국내+해외 | 유료만 전체 | 100건/일, 비상업 | 유료만 | ❌ 현재 단계 제외 |
| 연합뉴스·한경 RSS | 국내 | 요약 | 무제한 | 회색지대 | ❌ Google RSS로 대체 |

### 4.2 최종 선정 소스

| 소스 | 지역 | 용도 | 선정 이유 |
|------|------|------|----------|
| **Google News RSS (한국어)** | 국내 | 시장·종목 뉴스 | API 키 불필요, 무제한, 국내 주요 언론사 통합 커버리지 |
| **Naver News Search API** | 국내 | 관심 종목 뉴스 | 종목명 키워드 검색 특화, 25,000건/일 무료 |
| **Google News RSS (영어)** | 해외 | 글로벌 시장 뉴스 | API 키 불필요, 무제한, 글로벌 커버리지 |
| **Finnhub API** | 해외 | 해외 종목 뉴스 | ticker 기반 종목별 검색, 금융 특화, 무료 |

---

## 5. 수집 방법

### 5.1 소스별 수집 방법

#### Google News RSS

`feedparser` 라이브러리로 RSS XML을 파싱한다. API 키 없이 URL만으로 동작한다.

```python
import feedparser

# 국내 키워드 검색
url = f"https://news.google.com/rss/search?q={keyword}&hl=ko&gl=KR&ceid=KR:ko"

# 해외 키워드 검색
url = f"https://news.google.com/rss/search?q={keyword}&hl=en&gl=US&ceid=US:en"

feed = feedparser.parse(url)
for entry in feed.entries:
    # entry.title, entry.link, entry.summary, entry.published
```

수집 데이터: 제목(`title`), snippet(`summary`), URL(`link`), 발행일(`published`)

---

#### Naver News Search API

`httpx`로 REST API를 호출한다. 관심 종목명을 쿼리로 전송해 종목 특화 뉴스를 수집한다.

```python
import httpx

headers = {
    "X-Naver-Client-Id": settings.NAVER_CLIENT_ID,
    "X-Naver-Client-Secret": settings.NAVER_CLIENT_SECRET,
}
params = {"query": "삼성전자 실적", "display": 20, "sort": "date"}
response = httpx.get(
    "https://openapi.naver.com/v1/search/news.json",
    headers=headers,
    params=params,
)
```

수집 데이터: 제목(`title`), 발췌(`description`), URL(`link`), 발행일(`pubDate`)

---

#### Finnhub API

해외 종목 ticker와 날짜 범위로 종목별 뉴스를 수집한다.

```python
import httpx

# 종목별 뉴스
response = httpx.get(
    "https://finnhub.io/api/v1/company-news",
    params={
        "symbol": "AAPL",
        "from": "2026-05-01",
        "to": "2026-05-28",
        "token": settings.FINNHUB_API_KEY,
    },
)

# 일반 시장 뉴스
response = httpx.get(
    "https://finnhub.io/api/v1/news",
    params={"category": "general", "token": settings.FINNHUB_API_KEY},
)
```

수집 데이터: 제목(`headline`), 요약(`summary`), URL(`url`), 발행일(`datetime`)

---

### 5.2 수집 키워드 전략

키워드 설계는 수집 품질을 결정하는 핵심 변수다. 단순히 키워드 목록을 만드는 것이 아니라 **무엇을 왜 수집하는가**에 대한 구조적 사고가 필요하다.

**키워드 수 = API 호출 수 = 임베딩 비용**이 직결된다. 키워드 하나를 추가할 때마다 소스당 10~20건이 증가하고, 그 건수만큼 Vertex AI 임베딩 API를 추가 호출한다. 키워드는 넓게 잡되 **필요 최소한**으로 유지해야 한다.

---

#### 키워드 계층 구조

뉴스를 4개 레벨로 계층화한다. 상위 레벨일수록 모든 사용자에게 공통이고, 하위로 갈수록 개인화된다.

```
Level 1 — 거시경제        금리, 환율, 물가, 무역수지
              ↓ 영향
Level 2 — 시장·지수       코스피, 코스닥, 나스닥, S&P500
              ↓ 영향
Level 3 — 섹터            반도체, 2차전지, 바이오, 자동차
              ↓ 영향
Level 4 — 종목            삼성전자, SK하이닉스, NVDA (사용자 관심 기반)
```

이 구조의 핵심은 **상위 레벨 이슈가 하위 레벨에 영향을 준다**는 점이다.  
`"Fed 금리 인하"` 뉴스는 코스피를 거쳐 반도체 섹터 → 삼성전자에 영향을 미친다.  
Level 1~2는 모든 사용자에게 수집하고, Level 3~4는 서비스 커버리지·사용자 관심에 따라 수집한다.

---

#### Level 1 — 거시경제 키워드

시장 전체 방향성을 결정하는 핵심 지표. 발생 시 주가에 즉각적·광범위한 영향을 미친다.

```python
# 국내
DOMESTIC_MACRO_KEYWORDS = [
    # 금리 (방향성이 중요하므로 동결·인상·인하 모두 수집)
    "기준금리 인상", "기준금리 인하", "기준금리 동결",
    # 환율 (수출 기업 직접 영향)
    "원달러 환율 급등", "원달러 환율 급락",
    # 무역·물가
    "무역수지 흑자", "무역수지 적자", "소비자물가 상승",
    # 수급
    "외국인 순매수", "외국인 순매도",
]

# 해외
GLOBAL_MACRO_KEYWORDS = [
    # 연준 (미국 금리 결정은 전 세계 시장에 영향)
    "Fed rate hike", "Fed rate cut", "FOMC decision",
    # 미국 경기
    "US CPI", "US unemployment rate", "US GDP",
    # 중국 경기 (한국 수출 최대 영향국)
    "China PMI", "China export", "China stimulus",
    # 유가 (물가·에너지 비용 영향)
    "oil price surge", "OPEC production cut",
]
```

---

#### Level 2 — 시장·지수 키워드

지수 자체의 움직임과 함께 **왜 움직였는지** 원인 뉴스를 수집한다.

```python
MARKET_INDEX_KEYWORDS = [
    # 국내 지수
    "코스피 급등", "코스피 급락", "코스피 신고가",
    "코스닥 상한가", "코스닥 급락",
    # 해외 지수
    "나스닥 급락", "S&P500 랠리",
    "뉴욕증시 하락", "글로벌 증시",
]
```

지수 뉴스는 단순 방향보다 **원인 설명이 포함된 기사**가 분석에 유용하다.  
`"코스피 상승"`보다 `"코스피 급등 이유"` 형태의 기사가 LLM 분석 품질을 높인다.

---

#### Level 3 — 섹터 키워드

장독대가 커버하는 주요 섹터를 정의하고, 섹터별로 **투자 문맥이 담긴 복합 키워드**를 사용한다.

단순 키워드 vs 복합 키워드 비교:

| 단순 | 복합 | 차이 |
|------|------|------|
| `"반도체"` | `"반도체 업황"`, `"반도체 수출"` | 채용공고·강의 제외 |
| `"배터리"` | `"배터리 수주"`, `"2차전지 실적"` | 제품 리뷰 제외 |
| `"바이오"` | `"임상 승인"`, `"신약 허가"` | 일반 건강 기사 제외 |

```python
SECTOR_KEYWORDS = {
    "반도체": [
        "반도체 업황", "반도체 수출 증가", "메모리 반도체 가격",
        "파운드리 수주", "HBM 공급", "AI 반도체",
    ],
    "2차전지": [
        "배터리 수주", "2차전지 실적", "전기차 배터리 시장",
        "LFP 배터리", "전고체 배터리 상용화",
    ],
    "바이오": [
        "신약 임상 승인", "FDA 허가", "바이오 기술이전",
        "제약 실적", "항암제 임상",
    ],
    "자동차": [
        "자동차 수출 실적", "전기차 판매량", "완성차 영업이익",
    ],
    "조선": [
        "조선 수주 잔량", "LNG 선박 수주", "조선 수주 목표",
    ],
}
```

---

#### Level 4 — 종목 키워드 (동적, 3티어 차등 수집)

사용자 관심 종목 기반으로 동적 생성. **종목명 단독 사용 금지 — 반드시 수식어를 조합**한다.

```
❌ "삼성전자"      → 채용공고, 제품 광고, AS 안내까지 수집
✅ "삼성전자 주가" → 주가 변동, 목표주가, 투자의견 기사
✅ "삼성전자 실적" → 분기·연간 실적 발표 기사
```

모든 종목에 동일한 수집 전략을 적용하면 API 호출이 종목 수에 비례해 폭발한다. **관심도 기반 3티어**로 수집 강도를 차등화한다.

---

##### 티어 기준 및 수집 전략

| 티어 | 대상 | 수식어 | 수집 주기 | 기준 |
|------|------|--------|---------|------|
| **Tier 1** (핵심) | 상위 30종목 | `주가` + `실적` (2개) | 09:00 + 15:30 | 코스피200 시총 TOP 20 또는 서비스 내 관심 등록 상위 30 |
| **Tier 2** (일반) | 31~100번째 | `주가` (1개) | 15:30 만 | 관심 등록 중간 |
| **Tier 3** (관리) | 101번째~ | 없음 | 없음 | 섹터 키워드(Level 3)로 간접 커버 |

**Tier 3의 섹터 커버 원리**: 101번째 이후 종목은 개별 수집 없이 Level 3 섹터 키워드("반도체 업황", "배터리 수주" 등)가 관련 뉴스를 이미 포함한다. 해당 섹터의 이슈는 대표 종목과 동반 언급되는 경우가 많아 실질적 손실이 적다. 섹터 키워드로 수집된 기사에서 Tier 3 종목명이 언급되면 **06 뉴스 분석 단계의 Entity NER**(`company_tags` 추출)이 자동으로 해당 종목을 태깅한다 → 수집 키워드 없이도 종목 연결이 가능하다.

---

##### 티어 분류 로직

Tier 1 기준은 **시총 기반(정적) + 관심 기반(동적)** 두 가지를 병합한다.

```python
async def classify_stock_tiers(db) -> dict[str, list[str]]:
    # 코스피200 시총 TOP 20 (정적 — 주간 갱신)
    top_market_cap = await get_top_market_cap_symbols(limit=20)

    # 서비스 관심 등록 상위 30 (동적 — 일별 갱신)
    top_interested = await get_top_interested_symbols(db, limit=30)

    tier1 = list(set(top_market_cap) | set(top_interested))[:30]

    all_symbols = await get_all_tracked_symbols(db)
    remaining = [s for s in all_symbols if s not in tier1]

    return {
        "tier1": tier1,                  # ~30종목
        "tier2": remaining[:70],         # ~70종목
        "tier3": remaining[70:],         # 나머지
    }
```

---

##### 수집 실행 코드

```python
TIER_CONFIG = {
    "tier1": {"suffixes": ["주가", "실적"], "schedules": ["morning", "afternoon"]},
    "tier2": {"suffixes": ["주가"],         "schedules": ["afternoon"]},
    "tier3": {"suffixes": [],               "schedules": []},
}

async def collect_stock_news(schedule: str, tiers: dict):
    for tier, symbols in tiers.items():
        config = TIER_CONFIG[tier]
        if schedule not in config["schedules"]:
            continue
        for name in symbols:
            for suffix in config["suffixes"]:
                await naver_collector.collect(query=f"{name} {suffix}")
```

---

##### 수식어 선택 근거

수식어를 `주가`와 `실적` 두 개로 압축한 이유:

| 수식어 | 커버하는 뉴스 | 선택 이유 |
|--------|------------|---------|
| `주가` | 주가 변동, 목표주가, 투자의견, 매수/매도 리포트 | 종목 관련 뉴스 대부분 포함 |
| `실적` | 분기·연간 실적, 가이던스, 어닝서프라이즈 | 주린이에게 중요도 높음 |

수주·계약·합병·소송 등 이벤트성 키워드는 Level 3 섹터 키워드와 Level 1 거시 키워드가 이미 간접적으로 포함한다. Tier 1에서도 이 두 수식어면 핵심 종목 뉴스의 80% 이상을 커버한다.

---

#### 연관 키워드 — 공급망 기반 확장

**핵심 아이디어**: 직접 종목 키워드 외에 **공급망으로 연결된 해외 기업·이슈**도 수집한다.

예시:
- `NVDA 실적` → SK하이닉스 HBM 수요에 직접 영향
- `Apple 아이폰 판매량` → 삼성전자 OLED 패널 수요에 영향
- `테슬라 생산 감소` → LG에너지솔루션 배터리 수주에 영향

```python
# 기업별 공급망 연관 키워드 (초기 수동 정의, 이후 자동화 가능)
SUPPLY_CHAIN_KEYWORDS = {
    "SK하이닉스":      ["NVIDIA earnings", "HBM demand", "AI chip supply"],
    "삼성전자":        ["Apple iPhone sales", "TSMC earnings", "memory price"],
    "LG에너지솔루션":  ["Tesla production", "EV battery demand", "GM electric"],
    "현대차":          ["EV market share", "US EV incentive", "China EV sales"],
}

# 관심 종목이 공급망 맵에 있으면 연관 키워드도 수집
for symbol in tracked_symbols:
    if symbol in SUPPLY_CHAIN_KEYWORDS:
        for kw in SUPPLY_CHAIN_KEYWORDS[symbol]:
            await google_collector.collect_global(keyword=kw)
```

---

#### 이벤트 기반 임시 키워드

시장에는 **특정 기간에만 중요한 이슈**가 있다. 고정 키워드만으로는 이를 커버할 수 없다.

| 이벤트 | 활성화 기간 | 임시 키워드 |
|--------|-----------|------------|
| FOMC 회의 | 회의 전후 3일 | `"FOMC 결과"`, `"Fed 금리 결정"` |
| 국내 실적 시즌 | 1·4·7·10월 중순 | `"어닝서프라이즈"`, `"실적 쇼크"` |
| 미국 실적 시즌 | 분기 후 3~4주 | `"earnings beat"`, `"earnings miss"` |
| 금통위 | 회의 당일 | `"금통위 결정"`, `"한국 기준금리"` |

```python
# keywords/events.yaml 에서 관리
# 현재 날짜 기준으로 활성 이벤트 자동 반영
active_events = get_active_events(today)
for event in active_events:
    DOMESTIC_MACRO_KEYWORDS.extend(event.keywords)
```

---

#### 키워드 효과 측정 및 관리

키워드를 정의하는 것만큼 **얼마나 잘 동작하는지 측정**하는 것도 중요하다.

```
측정 지표: FilterChain 통과율 = 분석까지 통과한 뉴스 수 / 수집된 뉴스 수

통과율이 낮은 키워드 (< 20%) → 노이즈가 많음 → 더 좁은 복합 키워드로 교체
통과율이 높은 키워드 (> 80%) → 수집 범위가 너무 좁을 수 있음 → 범위 확장 검토
```

```python
# DB에 키워드별 수집·통과 카운트 기록
class KeywordStats(Base):
    __tablename__ = "keyword_stats"
    keyword        = Column(String(200), primary_key=True)
    collected      = Column(Integer, default=0)   # 수집된 기사 수
    passed_filter  = Column(Integer, default=0)   # FilterChain 통과 수
    date           = Column(Date, nullable=False)
```

**키워드 관리 사이클:**

```
정의 → 수집 → FilterChain 통과율 측정 → 분기 1회 리뷰 → 교체·추가
```

키워드는 코드가 아닌 `keywords/` 디렉토리의 YAML 파일로 관리해 코드 변경 없이 수정 가능하게 한다.

```yaml
# keywords/domestic_market.yaml
macro:
  - "기준금리 인상"
  - "기준금리 인하"
  - "원달러 환율 급등"

sector:
  반도체:
    - "반도체 업황"
    - "HBM 공급"
  2차전지:
    - "배터리 수주"
    - "전기차 배터리 시장"

events:
  fomc:
    active_dates: ["2026-06-11", "2026-06-12"]
    keywords: ["FOMC 결과", "Fed 금리 결정"]

# keywords/stock_tiers.yaml
tiers:
  tier1:
    # 코스피200 시총 TOP 20 + 관심 상위 — 주간 수동 갱신 후 동적 병합
    market_cap_top:
      - "005930"  # 삼성전자
      - "000660"  # SK하이닉스
      # ...
  tier2:
    # classify_stock_tiers() 결과 기반으로 자동 생성
    # 이 파일에 직접 목록을 관리하지 않음
  tier3:
    # 이하 동일
```

---

## 6. 주요 뉴스 선정 방법론

수집한 뉴스 전체를 분석 파이프라인에 넘기는 것은 비효율적이다. **"오늘 주목해야 할 뉴스"를 어떻게 선정할 것인가**는 서비스 품질을 결정하는 핵심 문제다.

### 6.1 타 서비스 벤치마크

#### 카카오 루빅스 (RUBICS)

카카오가 2015년 도입한 실시간 뉴스 추천 시스템. 가장 참고할 만한 국내 사례다.

> **핵심 로직**: "1시간 동안 같은 이슈로 묶인 기사 수가 많은 이슈를 주요 이슈로 선정한다"

기자들이 많이 쓴 주제 = 세상이 주목하는 이슈라는 논리다.

```
수집 → 클러스터링(유사 기사 묶기) → 클러스터 크기(기사 수) → 상위 6개 = 오늘의 주요 이슈
```

추가로 **실시간 사용자 반응**(클릭률, 체류 시간)을 반영해 순위를 조정한다. 또한 어뷰징(동일 기사 반복 송고) 필터링으로 인위적 볼륨 증폭을 차단한다.

---

#### Bloomberg Terminal

금융 전문 단말기. 알고리즘과 편집자를 함께 사용한다.

| 기능 | 방식 |
|------|------|
| **Top News** | 편집자가 직접 선별한 하루 핵심 뉴스 |
| **First Word** | 속보를 bullet point로 즉시 요약 |
| **감성 점수** | 뉴스별 긍정/부정 수치 제공 |
| **AI 3줄 요약** | 중요 기사를 자동으로 3문장 요약 |

블룸버그는 **속도(velocity)** 를 핵심 신호로 쓴다. 같은 종목에 기사가 갑자기 쏟아지면 상단에 노출된다.

---

#### 학술 연구 기반 — 중요도 신호 5가지

금융 뉴스 중요도 연구에서 공통적으로 등장하는 신호:

| 신호 | 정의 | 측정 방법 |
|------|------|----------|
| **Volume** | 같은 이슈 기사 수 | 클러스터 내 기사 수 |
| **Velocity** | 기사 발행 속도 | 단위 시간(1h)당 급증률 |
| **Sentiment** | 긍정/부정 강도 | FinBERT 감성 점수 |
| **Entity Prominence** | 언급된 기업 중요도 | 코스피200 여부, 시총 |
| **Social Signals** | SNS·검색 반응 | 구글 트렌드, 트위터 멘션 수 |

장독대 MVP에서는 **Volume + Velocity + LLM 판단** 3가지로 시작하고, 이후 Sentiment·Entity Prominence를 추가한다.

---

### 6.2 장독대 주요 뉴스 선정 로직

벤치마크 조사를 바탕으로 3단계 선정 로직을 채택한다.

```
[1단계] 볼륨 스코어링
  수집된 뉴스를 클러스터링 → 클러스터 크기(기사 수) = 이슈 볼륨 점수
  → 볼륨이 높을수록 많은 기자가 주목한 이슈

[2단계] 속도 스코어링
  이전 수집 대비 클러스터 증가율 계산
  → 급격히 커지는 클러스터 = 지금 터지고 있는 이슈

[3단계] LLM 최종 판단
  상위 클러스터를 FilterChain에 통과
  → "주린이에게 중요한가?" 최종 판단
  → 통과한 클러스터 = Issue Docent 생성 대상
```

```python
def score_cluster(cluster: list[News], prev_cluster_size: int) -> float:
    volume_score   = len(cluster)                              # 기사 수
    velocity_score = len(cluster) - prev_cluster_size          # 증가 속도
    return volume_score * 0.6 + velocity_score * 0.4
```

---

## 7. 뉴스 수집 에이전트

> 에이전트 오케스트레이션 전체 설계는 [`01-agent-orchestration-design.md`](./01-agent-orchestration-design.md) 참조.

`NewsCollectionAgent`는 `MasterOrchestrator`가 09:00, 15:30에 실행하는 LangGraph 기반 에이전트다.

### 7.1 에이전트 도구 (Tools)

| 도구 | 역할 |
|------|------|
| `search_tool(keyword, region)` | Google RSS / Naver / Finnhub 검색 |
| `cluster_tool(news_list)` | pgvector cosine similarity로 이슈 클러스터링 |
| `score_tool(clusters)` | 볼륨(기사 수) + 속도(증가율) 점수 계산 |
| `save_tool(news_list)` | News 테이블 UPSERT |

### 7.2 에이전트 플로우 (LangGraph)

```python
class NewsAgentState(TypedDict):
    schedule: str
    keywords: list[str]
    collected: list[dict]
    clusters: list[dict]
    scored: list[dict]
    top_issues: list[dict]
    errors: list[str]

workflow = StateGraph(NewsAgentState)
workflow.add_node("collect",  collect_node)
workflow.add_node("cluster",  cluster_node)
workflow.add_node("score",    score_node)
workflow.add_node("finalize", finalize_node)

workflow.set_entry_point("collect")
workflow.add_edge("collect",  "cluster")
workflow.add_edge("cluster",  "score")
workflow.add_edge("score",    "finalize")
workflow.add_edge("finalize", END)
```


## 8. 데이터 명세


### 8.1 수집·저장 필드 정의

| 필드명 | 타입 | 출처 | 설명 |
|--------|------|------|------|
| `title` | String(500) | 모든 소스 | 뉴스 제목 |
| `snippet` | Text | 모든 소스 | API 제공 snippet 또는 summary |
| `url` | String(500) | 모든 소스 | 원문 URL. **unique 제약으로 중복 방지** |
| `source` | String(100) | — | 소스 식별자 (`"google_rss_ko"` / `"naver"` / `"google_rss_en"` / `"finnhub"`) |
| `source_type` | String(50) | — | 뉴스 유형 (`"market_news"` / `"stock_news"`) |
| `region` | String(10) | — | 지역 (`"domestic"` / `"global"`) |
| `symbol` | String(20) | — | 종목 코드. 종목 뉴스만 값 있음 |
| `preprocessed_at` | DateTime(tz) | — | NULL=미처리. PreprocessingAgent 완료 시각 기록 |
| `is_analyzed` | Boolean | — | 분석 파이프라인 처리 여부. 기본값 `False` |
| `published_at` | DateTime | 모든 소스 | 기사 발행 시각 |
| `embedding` | Vector(768) | 임베딩 단계 | 제목·snippet 임베딩. pgvector 저장 |

| `original_url` | String(500), nullable | URL 정규화 전 원본. Google RSS 리다이렉트 URL 보존용 |

**저장하지 않는 것**: 본문 전체, 이미지, 기자명 (LLM 분석에 불필요하거나 저작권 리스크)

### 8.2 DB 스키마 (SQLAlchemy)

```python
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, UniqueConstraint
)
from pgvector.sqlalchemy import Vector
from app.db.database import Base


class News(Base):
    __tablename__ = "news"

    id               = Column(Integer, primary_key=True)
    title            = Column(String(500), nullable=False)
    snippet          = Column(Text, nullable=True)
    url              = Column(String(500), nullable=False)
    source           = Column(String(100), nullable=False)
    source_type      = Column(String(50), nullable=False)
    region           = Column(String(10), nullable=False)
    symbol           = Column(String(20), nullable=True)
    preprocessed_at  = Column(DateTime(timezone=True), nullable=True)  # NULL=미처리
    is_analyzed      = Column(Boolean, default=False)   # 분석 파이프라인 처리 여부
    published_at     = Column(DateTime(timezone=True), nullable=False)
    created_at       = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    embedding        = Column(Vector(768), nullable=True)

    original_url     = Column(String(500), nullable=True)  # Google RSS 리다이렉트 원본 URL

    __table_args__ = (UniqueConstraint("url"),)
```

#### 필수 인덱스

```sql
-- 중복 방지 (UniqueConstraint와 동일, 명시적 선언)
CREATE UNIQUE INDEX idx_news_url ON news (url);

-- 미처리 뉴스 조회 최적화 (분석 파이프라인이 자주 호출)
CREATE INDEX idx_news_unanalyzed ON news (is_analyzed, published_at DESC)
    WHERE is_analyzed = FALSE;

-- pgvector HNSW 인덱스 — 클러스터링·유사도 검색 성능 핵심
-- 인덱스 없으면 누적 벡터 수에 비례해 전체 스캔 발생
CREATE INDEX idx_news_embedding ON news USING hnsw (embedding vector_cosine_ops);
```

> HNSW 인덱스는 pgvector 활성화 직후 생성한다. 벡터가 수십만 건 쌓인 뒤 추가하면 인덱스 빌드 시간이 오래 걸린다.

### 8.3 텍스트 품질 전략

본문 전체 대신 snippet/summary를 사용하는 것이 분석 품질에 충분한지는 **실제 LLM 분석 결과를 확인한 후 판단**한다.

| 소스 텍스트 | 수준 | 특징 |
|------------|------|------|
| Google News snippet | 2~3문장 | 구글이 기사 핵심을 직접 추출. 단순 truncation이 아님 |
| Finnhub summary | 1~3문장 | 재무 이벤트 중심 요약. 금융 분석에 최적화 |
| Naver description | 짧은 발췌 | 첫 문장 위주. Google RSS snippet으로 보완 |

품질 부족 시 대응 옵션:

| 옵션 | 방법 | 비용 |
|------|------|------|
| A. 프롬프트 최적화 | snippet에 맞게 분석 프롬프트 개선 | 없음 |
| B. trafilatura 도입 | 수집 시 본문 추출 후 LLM 요약 → 요약만 저장 | 저작권 회색지대, LLM 비용 |

→ **현재는 A → B 순서로 검토한다.**

---

## 9. 수집 주기

한국 주식 시장 운영 시간(09:00~15:20)을 기준으로 하루 2회 수집한다.

| 시점 | 수집 내용 | 이유 |
|------|----------|------|
| **09:00** | 전일 야간 뉴스 + 당일 프리마켓 뉴스 | 장 시작 전 이슈 파악 |
| **15:30** | 당일 장 중 뉴스 전체 + 분석 파이프라인 트리거 | 장 마감(15:20) 직후 당일 전체 분석 |

스케줄링은 **Airflow DAG**가 담당한다. 상세 DAG 정의는 [`01-agent-orchestration-design.md`](./01-agent-orchestration-design.md) 섹션 3.3 참조.

```python
# dags/jangdokdae_morning.py — Airflow cron 예시
schedule_interval="0 9 * * 1-5"   # 평일 09:00 KST
schedule_interval="30 15 * * 1-5"  # 평일 15:30 KST
```

---

## 10. 시스템 아키텍처

### 10.1 전체 멀티 에이전트 구조

수집·전처리·임베딩을 각각 독립된 에이전트로 분리하고, `MasterOrchestrator`가 전체를 조율한다.

```
dags/                              ← Airflow DAG (스케줄링 담당)
  ├── jangdokdae_morning.py      ← 09:00 평일
  ├── jangdokdae_afternoon.py    ← 15:30 평일
  └── jangdokdae_market_close.py ← 16:30 평일

services/
  ├── master_orchestrator.py              ← MasterOrchestrator  ⭐ 전체 조율
  │
  ├── agents/
  │   ├── news_collection_agent.py        ← NewsCollectionAgent (LangGraph)
  │   ├── company_collection_agent.py     ← CompanyCollectionAgent (LangGraph)
  │   ├── preprocessing_agent.py        ← PreprocessingAgent
  │   └── embedding_clustering_agent.py   ← EmbeddingClusteringAgent
  │
  ├── collector/               ← 수집기 (에이전트 도구로 사용)
  │   ├── tools/
  │   │   ├── search_tool.py   ← Google RSS / Naver / Finnhub 검색
  │   │   ├── dart_tool.py     ← DART 공시 수집
  │   │   ├── stock_tool.py    ← 주가 수집 (FinanceDataReader)
  │   │   ├── macro_tool.py    ← 환율·금리 수집
  │   │   ├── cluster_tool.py  ← 클러스터링 + 볼륨 스코어
  │   │   ├── expand_tool.py   ← 추가 키워드 검색
  │   │   └── save_tool.py     ← DB UPSERT
  │   ├── google_news_collector.py
  │   ├── naver_collector.py
  │   └── finnhub_collector.py
  │
  ├── preprocessor/            ← 전처리기 (PreprocessingAgent 도구)
  │   ├── deduplicator.py
  │   ├── filter.py
  │   └── normalizer.py
  │
  └── embedder/                ← 임베더 (EmbeddingClusteringAgent 도구로 사용)
      ├── news_embedder.py
      └── cluster.py
```

---

### 10.2 MasterOrchestrator 역할

에이전트들의 **실행 순서·타이밍·의존성**을 관리한다.  
에이전트끼리 직접 통신하지 않는다. **공유 DB를 통해 데이터를 전달**한다.

```python
class MasterOrchestrator:
    async def run_morning(self) -> None:
        """09:00 — 장 시작 전"""
        await asyncio.gather(
            self.news_agent.run("morning"),
            self.company_agent.run("morning"),
        )
        # 전처리는 수집 인라인 실행 (04-preprocessing-design.md 참조)
        await self.embedding_agent.run()

    async def run_afternoon(self) -> None:
        """15:30 — 장 마감 직후"""
        await asyncio.gather(
            self.news_agent.run("afternoon"),
            self.company_agent.run("afternoon"),
        )
        # 전처리는 수집 인라인 실행 (04-preprocessing-design.md 참조)
        await self.embedding_agent.run()
        await self._trigger_analysis_pipeline()

    async def run_market_close(self) -> None:
        """16:30 — 주가·거시지표 수집 (전처리·임베딩 불필요)"""
        await self.company_agent.run("market_close")
```

**에이전트 간 의존성:**

```
NewsCollectionAgent   ─┐
                        ├→ DB 저장 (원시, preprocessed_at=NULL) → PreprocessingAgent → EmbeddingClusteringAgent
CompanyCollectionAgent ─┘                                        ↓
                                                       분석 파이프라인 트리거
```

---

### 10.3 에이전트 상세 설계 참조

각 에이전트의 상태, 노드, 플로우, 에러 처리는 별도 문서를 참조한다.

→ [`01-agent-orchestration-design.md`](./01-agent-orchestration-design.md)


## 11. 구현 로드맵

에이전트별로 독립 구현 후 `MasterOrchestrator`로 통합한다.

### Phase 1 — 수집기 도구 구현

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 1 | API 키 발급 (Naver, Finnhub), `.env` 등록 | `.env` |
| 2 | `GoogleNewsCollector` 구현 | `services/collector/google_news_collector.py` |
| 3 | `NaverCollector` 구현 | `services/collector/naver_collector.py` |
| 4 | `FinnhubCollector` 구현 | `services/collector/finnhub_collector.py` |
| 5 | `normalizer.py` 구현 | `services/preprocessor/normalizer.py` |
| 6 | `search_tool`, `save_tool` 구현 | `services/collector/tools/` |
| 7 | DB 스키마 반영 (`News`, `KeywordStats`) | `app/db/models.py` |
| 8 | 종목 티어 분류 함수 구현 (`classify_stock_tiers`) | `services/collector/tier.py` |

### Phase 2 — NewsCollectionAgent 구현

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 8 | pgvector 활성화 | DB 마이그레이션 |
| 9 | `news_embedder.py`, `cluster.py` 구현 | `services/embedder/` |
| 10 | `cluster_tool`, `score_tool` 구현 | `services/collector/tools/` |
| 11 | `NewsCollectionAgent` LangGraph 노드 구현 | `services/agents/news_collection_agent.py` |

### Phase 3 — 전처리 모듈 + EmbeddingClusteringAgent 구현

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 13 | `deduplicator.py`, `filter.py` 구현 | `services/preprocessor/` |
| 14 | `PreprocessingAgent` 구현 | `services/agents/preprocessing_agent.py` |
| 15 | `EmbeddingClusteringAgent` 구현 | `services/agents/embedding_clustering_agent.py` |

### Phase 4 — MasterOrchestrator 통합

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 16 | `MasterOrchestrator` 구현 | `services/master_orchestrator.py` |
| 17 | Airflow DAG 작성 (09:00 / 15:30 / 16:30) | `dags/` |
| 18 | 키워드 통과율 집계 | `app/db/queries.py` |

### Phase 5 — 텍스트 품질 검증

| 조건 | 대응 방안 |
|------|----------|
| snippet으로 LLM 분석 품질 충분 | 현행 유지 |
| 품질 부족 | 프롬프트 최적화 → trafilatura → GNews 유료 순서로 검토 |


## 12. 미결 사항

| 항목 | 내용 | 결정 시점 |
|------|------|----------|
| 임베딩 모델 선정 | `text-multilingual-embedding-002` 1순위 후보, 확정 필요 | Phase 2 시작 전 |
| 클러스터링 임계값 | 실제 뉴스 100건으로 교정 테스트 후 결정 | Phase 2 구현 후 |
| 텍스트 품질 충분 여부 | snippet으로 LLM 분석 품질 검증 | Phase 1 구현 후 테스트 |
| 관심 종목 없는 초기 사용자 대응 | 기본 키워드 뉴스만 제공할지 여부 | 기획 논의 필요 |

---

## 참고 자료

- [Google News RSS 가이드](https://news.google.com/rss)
- [Naver 뉴스 검색 API](https://developers.naver.com/docs/serviceapi/search/news/news.md)
- [Finnhub API 문서](https://finnhub.io/docs/api)
- [Neon pgvector 공식 문서](https://neon.com/docs/extensions/pgvector)
- [디지털 뉴스콘텐츠 이용규칙 (한국언론진흥재단)](https://www.kpf.or.kr/front/board/boardContentsView.do?board_id=291&contents_id=855b0c963b5c4a42ba6b26d06c7186d4)
- [웹크롤링 법적 판단 기준 — 대법원 2021도1533](https://atlaw.kr/kr-blog/%EC%9B%B9%ED%81%AC%EB%A1%A4%EB%A7%81%EC%9D%98-%ED%98%95%EC%82%AC%EC%B2%98%EB%B2%8C-%EA%B0%80%EB%8A%A5%EC%84%B1-%EB%8C%80%EB%B2%95%EC%9B%90-2021%EB%8F%841533-%ED%8C%90%EA%B2%B0-%EC%99%84%EC%A0%84/)
