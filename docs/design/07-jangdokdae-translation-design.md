# 주린이 번역 기획서

**작성일** 2026-05-28  
**기획 범위** Issue Docent → 주린이 번역 콘텐츠 → 퀴즈 → 다음 이슈 추천  
**관련 문서**  
- [에이전트 오케스트레이션 아키텍처](./01-agent-orchestration-design.md)
- [뉴스 분석 기획서](./06-news-analysis-design.md)

---

## 목차

- [1. 기능 개요](#1-기능-개요)
- [2. 기획 의도](#2-기획-의도)
- [3. 핵심 사용자 흐름](#3-핵심-사용자-흐름)
- [4. 전체 페이지 경험](#4-전체-페이지-경험)
- [5. 주요 기능 상세](#5-주요-기능-상세)
- [6. 화면 구성](#6-화면-구성)
- [7. 콘텐츠 작성 기준](#7-콘텐츠-작성-기준)
- [8. 데이터 명세](#8-데이터-명세)
- [9. LLM 생성 파이프라인](#9-llm-생성-파이프라인)
- [10. 추천 알고리즘](#10-추천-알고리즘)
- [11. 구현 로드맵](#11-구현-로드맵)
- [12. 개발 범위 및 추후 확장](#12-개발-범위-및-추후-확장)
- [13. 미결 사항](#13-미결-사항)

---

## 1. 기능 개요

`주린이 번역`은 주식 뉴스를 단순히 요약해주는 기능이 아니라, 주식 입문자가 뉴스를 이해하고 해석할 수 있도록 돕는 **학습형 콘텐츠 기능**이다.

사용자는 주식 뉴스를 콘텐츠처럼 가볍게 읽고, 본문 안의 용어 풀이와 `전문가의 시각`을 통해 뉴스의 의미를 이해한 뒤, 퀴즈를 통해 이해도를 확인하고 다음 이슈로 이어진다.

파이프라인에서의 위치:

```
뉴스 분석 (Issue Docent 생성) → [주린이 번역] → 사용자 화면 제공
```

---

## 2. 기획 의도

주식 입문자는 뉴스를 읽어도 용어, 문장, 맥락을 이해하기 어렵고, 뉴스가 주가나 시장에 어떤 의미를 갖는지 판단하기 어렵다.

`주린이 번역`은 전문가가 뉴스를 읽고 해석하는 관점을 주식 입문자가 이해할 수 있는 방식으로 전달하여, 사용자가 **주식 지식과 뉴스 해석력을 자연스럽게 쌓도록** 돕는다.

---

## 3. 핵심 사용자 흐름

```
이슈 선택 → 콘텐츠 이해 → 이해도 확인 → 학습 완료 → 다음 이슈 계속
```

1. 사용자는 주식 뉴스 이슈를 선택한다.
2. 미니멀한 콘텐츠 페이지에서 제목과 본문 중심으로 뉴스를 읽는다.
3. 본문 안의 주식 용어를 클릭해 용어 설명을 확인한다.
4. `전문가의 시각`을 통해 뉴스의 핵심 해석을 이해한다.
5. `이해도 확인하기`를 통해 별도 퀴즈 페이지로 이동한다.
6. 퀴즈 완료 후 관련 이슈와 관심 기반 이슈를 추천받는다.

---

## 4. 전체 페이지 경험

`주린이 번역` 페이지는 일반적인 뉴스 상세 페이지가 아니라, 하나의 주식 이슈를 **콘텐츠처럼 가볍게 소비하는 페이지**로 설계한다.

페이지는 제목과 본문 중심으로 구성하고, 용어 풀이와 전문가의 시각은 사용자의 읽는 흐름을 방해하지 않는 보조 요소로 제공한다.

```
이슈 선택 → 콘텐츠 페이지 → 퀴즈 페이지 → 다음 이슈 추천
```

---

## 5. 주요 기능 상세

### 5.1 주식 용어 풀이

본문 안에 등장하는 주식 용어를 클릭하면 주식 용어 사전에 등록된 설명을 제공한다.

**동작 방식:**

- 용어 설명은 뉴스마다 새로 생성하지 않고, 서비스 차원에서 구축한 `주식 용어 사전`의 기본 정의를 기반으로 제공한다.
- 뉴스 본문과 주식 용어 사전을 매칭한 뒤, 실제 본문에서 클릭 가능하게 표시할 용어는 **LLM이 선별**한다.

**LLM 용어 선별 기준:**

| 기준 | 설명 |
|------|------|
| 사전 등록 여부 | 주식 용어 사전에 등록된 용어만 대상 |
| 주식/투자 의미 사용 여부 | 일반 의미가 아닌 주식 도메인 의미로 사용된 경우만 선별 |
| 사용자 이해 필요성 | 주린이가 모를 가능성이 높은 용어 우선 |
| 본문 가독성 | 지나치게 많은 용어 강조는 제외 (최대 5개 권장) |
| 중복 여부 | 동일 용어는 첫 등장 시에만 표시 |

---

### 5.2 전문가의 시각

`전문가의 시각`은 전문가가 뉴스를 읽고 얻는 핵심 해석을 주식 입문자가 이해하기 쉽게 풀어주는 영역이다.

단순히 "전문가가 본 포인트"를 나열하는 것이 아니라, **본문 안의 어떤 표현·숫자·변화 포인트를 근거로 그런 해석이 나왔는지** 함께 설명한다.

**구성:**

- 기본 **1개** 제공, 복잡한 뉴스에서는 최대 **3개**까지 제공
- 각 포인트는 `제목 + 해설` 구조

```
[전문가의 시각 포인트 구조]
  제목:  전문가가 본 핵심 해석 (한 문장)
  해설:  해당 해석의 근거와 의미 (2~4문장)
  근거:  본문 내 연결된 표현·숫자·변화 포인트 (highlight_ids)
```

---

### 5.3 본문 근거 강조

사용자가 `전문가의 시각` 포인트를 선택하면, 해당 해석과 연결된 **본문 내 표현·문장·숫자·변화 포인트가 강조**된다.

이를 통해 사용자는 전문가가 어떤 근거를 보고 해당 해석을 도출했는지 확인할 수 있다.

- 전문가의 시각은 문단 단위로 고정하지 않고, 필요한 본문 요소만 연결한다.
- 근거 연결은 본문의 `span` 단위로 처리한다 (`highlight_id` 기반).

---

### 5.4 이해도 확인 퀴즈

퀴즈는 뉴스 콘텐츠 페이지 하단에 직접 노출하지 않고, `이해도 확인하기` 버튼을 통해 **별도 퀴즈 페이지**로 이동해 제공한다.

**퀴즈 구성 (3문항):**

| 번호 | 유형 | 출제 기준 |
|------|------|---------|
| 1 | 주식 용어 퀴즈 | 해당 콘텐츠에서 실제 노출된 용어 중 1개 선택 |
| 2 | 뉴스 이해 퀴즈 | `전문가의 시각`에서 다룬 핵심 포인트 기반 |
| 3 | 종목·섹터 도메인 기초 상식 퀴즈 | sector_tags 기반 기초 상식 |

- 난이도 표시는 제외한다.
- 퀴즈 완료 후 정답/오답 피드백과 간단한 해설을 제공한다.

---

### 5.5 다음 이슈 추천

퀴즈 완료 후 사용자가 다음 콘텐츠로 자연스럽게 이어질 수 있도록 총 **4개의 이슈**를 추천한다.

| 추천 유형 | 수 | 기준 |
|---------|---|------|
| 관련 이슈 | 2개 | 같은 종목·섹터·테마·시장 이슈 |
| 관심 기반 이슈 | 1개 | 온보딩에서 선택한 관심 종목·섹터 |
| 관련 없는 이슈 | 1개 | 다양한 이슈 노출을 위한 랜덤 |

> 학습 연결 이슈(학습 진척 기반 추천)는 초기 범위에서 제외한다.

---

## 6. 화면 구성

### 6.1 이슈 피드

사용자는 주식 뉴스 이슈를 피드에서 확인하고 선택한다. 피드는 칼럼형 콘텐츠보다 **실제 주식 뉴스 이슈 중심**으로 구성한다.

### 6.2 콘텐츠 페이지

제목과 본문 중심의 미니멀한 구조로 제공한다.

| 영역 | 설명 |
|------|------|
| 본문 | 주린이용 번역 텍스트, 용어 클릭 가능 표시 |
| 전문가의 시각 | 웹: 오른쪽 사이드 패널 / 모바일: 본문 하단 카드 또는 접이식 영역 |
| 이해도 확인하기 | 퀴즈 페이지로 이동하는 버튼 |

### 6.3 퀴즈 페이지

콘텐츠 페이지와 분리된 별도 화면으로 제공한다. 용어 이해와 뉴스 해석 이해를 확인하는 역할을 한다.

### 6.4 퀴즈 완료 페이지

퀴즈 완료 후 정답/오답 결과와 해설을 제공한다. 이후 `다음에 볼 이슈` 영역을 통해 다음 이슈 4개를 추천한다.

---

## 7. 콘텐츠 작성 기준

### 7.1 전문가의 시각 작성 기준

| 항목 | 기준 |
|------|------|
| 제목 | 전문가가 본 핵심 해석을 한 문장으로 요약 |
| 해설 | 해당 해석의 근거와 의미를 설명. 2~4문장 권장 |
| 투자 판단 표현 | "매수해야 한다", "확실히 오른다" 금지 |
| 허용 표현 | "부담으로 작용할 수 있다", "긍정적으로 해석될 수 있다", "추가 확인이 필요하다" |

### 7.2 용어 설명 작성 기준

| 항목 | 기준 |
|------|------|
| 정확성 | 용어의 기본 의미를 정확히 설명 |
| 언어 수준 | 주식 입문자가 이해할 수 있는 문장으로 작성 |
| 도메인 용어 최소화 | 용어 설명 안에 또 다른 주식 용어 사용 최소화 |
| 맥락 독립성 | 특정 뉴스 맥락에 과도하게 종속되지 않도록 작성 |
| 투자 판단 배제 | 투자 판단을 유도하는 표현 금지 |

### 7.3 퀴즈 출제 기준

| 항목 | 기준 |
|------|------|
| 용어 퀴즈 대상 | 해당 콘텐츠에서 실제로 노출된 용어 중 1개 선택 |
| 뉴스 이해 퀴즈 | `전문가의 시각`에서 다룬 핵심 포인트 기반 출제 |
| 문제 유형 | 단순 암기·일반 상식 금지. 이해 여부 확인 중심 |
| 해설 필수 | 정답/오답 이후 반드시 짧은 해설 제공 |
| 오답 선택지 | 그럴듯해 보이지만 핵심을 빗나간 항목으로 구성 |

---

## 8. 데이터 명세

### 8.1 ExpertView 테이블

전문가의 시각 데이터를 저장한다.

```python
from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from app.db.database import Base


class ExpertView(Base):
    __tablename__ = "expert_views"

    id              = Column(Integer, primary_key=True)
    docent_id       = Column(Integer, ForeignKey("issue_docent.id"), nullable=False)
    order           = Column(Integer, nullable=False)       # 1~3, 표시 순서
    title           = Column(String(200), nullable=False)   # 핵심 해석 한 문장
    description     = Column(Text, nullable=False)          # 해설 2~4문장
    highlight_ids   = Column(ARRAY(String), nullable=False, default=[])  # 본문 근거 span IDs
```

### 8.2 TermHighlight 테이블

LLM이 선별한 본문 내 용어 강조 정보를 저장한다.

```python
class TermHighlight(Base):
    __tablename__ = "term_highlights"

    id              = Column(Integer, primary_key=True)
    docent_id       = Column(Integer, ForeignKey("issue_docent.id"), nullable=False)
    term            = Column(String(100), nullable=False)   # 용어명
    term_dict_id    = Column(Integer, ForeignKey("stock_terms.id"), nullable=False)
    span_id         = Column(String(50), nullable=False)    # 본문 내 span ID
    position        = Column(Integer, nullable=False)       # 본문 내 등장 순서
```

### 8.3 StockTerm 테이블

서비스 차원에서 구축하는 주식 용어 사전.

```python
class StockTerm(Base):
    __tablename__ = "stock_terms"

    id              = Column(Integer, primary_key=True)
    term            = Column(String(100), nullable=False, unique=True)
    definition      = Column(Text, nullable=False)          # 주식 입문자 대상 설명
    category        = Column(String(50), nullable=True)     # 기초개념, 재무, 시장용어, ...
    created_at      = Column(DateTime(timezone=True), nullable=False)
    updated_at      = Column(DateTime(timezone=True), nullable=True)
```

### 8.4 Quiz 테이블

```python
class Quiz(Base):
    __tablename__ = "quizzes"

    id              = Column(Integer, primary_key=True)
    docent_id       = Column(Integer, ForeignKey("issue_docent.id"), nullable=False)
    quiz_type       = Column(String(20), nullable=False)    # term | news_comprehension | sector_knowledge
    question        = Column(Text, nullable=False)
    options         = Column(JSONB, nullable=False)          # [{text, is_correct}]
    explanation     = Column(Text, nullable=False)           # 정답 해설
    order           = Column(Integer, nullable=False)        # 1~3
```

### 8.5 IssueRecommendation 테이블

다음 이슈 추천 결과를 저장한다.

```python
class IssueRecommendation(Base):
    __tablename__ = "issue_recommendations"

    id              = Column(Integer, primary_key=True)
    source_docent_id = Column(Integer, ForeignKey("issue_docent.id"), nullable=False)
    recommended_docent_id = Column(Integer, ForeignKey("issue_docent.id"), nullable=False)
    rec_type        = Column(String(20), nullable=False)  # related | interest_based | random
    score           = Column(Float, nullable=True)
    created_at      = Column(DateTime(timezone=True), nullable=False)
```

### 8.6 API 응답 구조

```python
# GET /api/docent/{docent_id}
{
    "docent": {
        "id": 1,
        "title": "삼성전자 3분기 영업이익 9.2조",
        "l1_type": "기업",
        "content_body": {...},          # 4 head 본문
        "term_highlights": [            # LLM 선별 용어
            {"span_id": "s1", "term": "영업이익", "definition": "..."}
        ],
        "expert_views": [               # 전문가의 시각 1~3개
            {"order": 1, "title": "...", "description": "...", "highlight_ids": ["s3"]}
        ]
    }
}

# GET /api/docent/{docent_id}/quiz
{
    "quizzes": [
        {"order": 1, "quiz_type": "term", "question": "...", "options": [...]}
    ]
}

# GET /api/docent/{docent_id}/recommendations
{
    "recommendations": [
        {"docent_id": 2, "rec_type": "related", "title": "..."},
        {"docent_id": 3, "rec_type": "related", "title": "..."},
        {"docent_id": 4, "rec_type": "interest_based", "title": "..."},
        {"docent_id": 5, "rec_type": "random", "title": "..."}
    ]
}
```

---

## 9. LLM 생성 파이프라인

`NewsAnalysisAgent`가 Issue Docent를 발행한 후, 주린이 번역 콘텐츠는 추가 LLM 호출로 생성된다.

```
Issue Docent 발행
  ↓
[TranslationChain]
  ├── 용어 선별 (select_terms_tool)     → TermHighlight 저장
  ├── 전문가 시각 생성 (expert_view_tool) → ExpertView 저장
  └── 퀴즈 생성 (quiz_tool)             → Quiz 저장
  ↓
추천 데이터 생성 (recommendation_tool)  → IssueRecommendation 저장
```

**프롬프트 파일 구조:**

```yaml
# prompts/select_terms.yaml
# 본문에서 주식 용어 사전 매칭 후 노출 용어 선별
# 입력: 본문 텍스트, 용어 사전 목록
# 출력: [{span_id, term, reason}]

# prompts/expert_view.yaml
# 전문가의 시각 1~3개 생성
# 입력: 본문, L2 프레임, l3 태그
# 출력: [{title, description, highlight_ids}]

# prompts/quiz_generate.yaml
# 퀴즈 3문항 생성
# 입력: 본문, expert_views, term_highlights, sector_tags
# 출력: [{quiz_type, question, options, explanation}]
```

---

## 10. 추천 알고리즘

다음 이슈 4개를 선정하는 기준.

### 관련 이슈 2개 — 벡터 유사도 기반

```python
# pgvector cosine similarity로 유사 Docent 검색
# 조건: 같은 sector_tags OR company_tags(primary) 겹침
# 정렬: embedding 유사도 내림차순
# 제외: 이미 사용자가 읽은 docent
SELECT d.id, d.title,
       d.embedding <=> current.embedding AS distance
FROM issue_docent d
WHERE d.id != :current_id
  AND d.sector_tags && :current_sector_tags  -- 섹터 겹침
ORDER BY distance
LIMIT 2;
```

### 관심 기반 이슈 1개 — 사용자 관심 종목·섹터

```python
# 온보딩에서 등록한 관심 종목/섹터 기반
# company_tags(primary)가 관심 종목에 포함되거나
# sector_tags가 관심 섹터에 포함된 최신 docent
SELECT d.id, d.title
FROM issue_docent d
WHERE (d.company_tags @> :user_interests     -- 관심 종목
    OR d.sector_tags && :user_sectors)       -- 관심 섹터
  AND d.id != :current_id
ORDER BY d.published_at DESC
LIMIT 1;
```

### 관련 없는 이슈 1개 — 섹터 다양성 보장

```python
# 현재 이슈와 섹터가 겹치지 않는 최신 docent 중 랜덤
SELECT d.id, d.title
FROM issue_docent d
WHERE NOT (d.sector_tags && :current_sector_tags)
  AND d.id != :current_id
ORDER BY RANDOM()
LIMIT 1;
```

---

## 11. 구현 로드맵

### Phase 1 — 데이터 구조 및 용어 사전

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 1 | `StockTerm`, `TermHighlight`, `ExpertView`, `Quiz`, `IssueRecommendation` 테이블 생성 | `app/db/models.py` + Alembic |
| 2 | 주식 용어 사전 초기 데이터 구축 (기초 용어 100개 이상) | `stock_terms` 초기 데이터 |
| 3 | `select_terms.yaml` 프롬프트 작성 및 테스트 | `prompts/select_terms.yaml` |

### Phase 2 — 전문가의 시각 & 퀴즈 생성

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 4 | `expert_view.yaml` 프롬프트 작성 | `prompts/expert_view.yaml` |
| 5 | `quiz_generate.yaml` 프롬프트 작성 | `prompts/quiz_generate.yaml` |
| 6 | `TranslationChain` 구현 | `services/chains/translation_chain.py` |
| 7 | 샘플 50건 생성 후 품질 검토 | 수동 검토 |

### Phase 3 — API 및 추천

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 8 | `GET /api/docent/{id}` API 구현 | `app/api/docent.py` |
| 9 | `GET /api/docent/{id}/quiz` API 구현 | `app/api/docent.py` |
| 10 | 추천 쿼리 구현 | `app/db/queries.py` |
| 11 | `GET /api/docent/{id}/recommendations` API 구현 | `app/api/docent.py` |

### Phase 4 — NewsAnalysisAgent 연결

| 단계 | 내용 | 산출물 |
|------|------|--------|
| 12 | Issue Docent 발행 후 `TranslationChain` 자동 실행 연결 | `services/agents/news_analysis_agent.py` |
| 13 | 본문 span ID 매핑 구조 확정 | 프론트엔드 협의 필요 |

---

## 12. 개발 범위 및 추후 확장

### 초기 범위

- 주식 뉴스 이슈 피드
- 콘텐츠 페이지 (본문 + 용어 강조 + 전문가의 시각)
- 주식 용어 사전 기반 용어 풀이
- LLM 기반 용어 노출 선별
- 전문가의 시각 최대 3개 제공
- 전문가의 시각 선택 시 본문 근거 강조
- 별도 퀴즈 페이지 (3문항)
- 퀴즈 완료 후 다음 이슈 4개 추천

### 추후 확장

| 항목 | 내용 |
|------|------|
| 학습 기록 | 사용자별 퀴즈 기록 저장 및 오답 복습 |
| 개인화 강화 | 관심 종목 기반 피드 개인화 |
| 품질 피드백 | 전문가의 시각 품질 피드백 기능 |
| 용어 사전 페이지 | 독립적인 주식 용어 사전 검색 페이지 |
| 연속 읽기 | 이슈 연속 시청/읽기 경험 고도화 |
| 학습 진척 추천 | 자주 틀린 용어·이해 부족 이슈 기반 추천 |

---

## 13. 미결 사항

| 항목 | 내용 | 결정 시점 |
|------|------|----------|
| 본문 span ID 구조 | 프론트엔드와 본문 근거 강조 연결 방식 협의 필요 | Phase 3 전 |
| 용어 사전 초기 범위 | 몇 개부터 시작할지, 카테고리 분류 | Phase 1 전 |
| 퀴즈 문항 수 확정 | 기획서에 2문항/3문항 혼재 — 3문항으로 확정 여부 | Phase 2 전 |
| 관련 없는 이슈 선정 방식 | 완전 랜덤 vs 읽지 않은 이슈 중 편집 추천 | Phase 3 전 |
| 전문가의 시각 개수 기준 | "복잡한 뉴스" 판단 기준 자동화 방법 | Phase 2 구현 시 |
