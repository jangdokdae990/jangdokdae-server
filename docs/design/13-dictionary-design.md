# 13. 용어 사전 설계

이 문서는 `issue_docent.term_spans`에서 나온 용어를 사용자에게 설명하고, `/dictionary` 화면과 Issue Detail 툴팁이 같은 저장소를 보도록 만들기 위한 최소 설계다.

## 1. 배경

현재 콘텐츠 파이프라인은 용어를 두 군데에 남긴다.

| 위치 | 현재 의미 |
| --- | --- |
| `news_analysis.term_tags` | 클러스터 분석 단계에서 고른 설명 필요 용어 목록 |
| `issue_docent.term_spans` | 생성 본문 안에 실제 등장한 용어와 사용 문장 `[{term, sentence}]` |

하지만 현재 DB에는 dictionary table이 없다. 그래서 Issue Detail API는 임시로 `definition="준비 중인 용어입니다."`를 내려준다.

## 2. 목표

- Issue Detail 본문에서 용어를 클릭하면 tooltip으로 설명을 보여준다.
- `/dictionary` 화면은 같은 용어 저장소를 검색한다.
- `term_spans`에 나온 용어가 사전에 없으면 생성 후보로 쌓는다.
- 기존 `9990-jangdokdae/dictionary` 레포 방식은 그대로 복사하지 않는다.
- 사전은 **주식/금융 용어**와 **도메인 용어**를 분리한다.

## 3. 용어 타입

| 타입 | 의미 | 예시 |
| --- | --- | --- |
| `finance` | 투자, 금융, 시장 구조를 이해하는 데 필요한 범용 용어 | 기준금리, PER, ETF, 실적 컨센서스 |
| `domain` | 특정 산업/뉴스 맥락을 이해하는 데 필요한 도메인 용어 | HBM, 양극재, 바이오시밀러, LNG선 |

타입은 UI 장식만이 아니라 검색/필터, 검수 큐, 향후 퀴즈 생성 범위에 직접 영향을 준다.

## 4. 최소 테이블

1차는 테이블 하나로 충분하다.

```text
dictionary_terms
- id
- term
- term_type        finance | domain
- definition
- example
- source           llm | manual | imported
- status           candidate | approved | rejected
- first_issue_docent_id
- created_at
- updated_at
```

제약:

- `term`은 중복 방지를 위해 unique로 둔다.
- 같은 표기라도 의미가 갈라지는 경우는 마감 이후 `term_aliases` 또는 disambiguation으로 확장한다.
- `definition`은 `candidate` 상태에서도 채울 수 있지만, UI에서 확정 설명으로 쓰는 기본값은 `approved` 우선이다.

## 5. 용어 설명 생성·적재 흐름

```text
issue_docent.term_spans
  → term 값만 추출
  → distinct term 중복 제거
  → dictionary_terms.term 미존재 확인
  → Google Vertex AI로 주린이용 정의/예시 생성
  → status=candidate 저장
  → 검수 후 approved
```

마감 전 최소 구현은 아래 정도면 충분하다.

- Issue Detail API는 `approved` 정의가 있으면 사용한다.
- 없으면 기존 fallback인 `"준비 중인 용어입니다."`를 유지한다.
- 후보를 정리한 뒤 용어마다 설명과 예시를 생성해 `dictionary_terms`에 적재한다.
- 생성은 백필 스크립트(`scripts/backfill_dictionary_terms.py`)와 수동 API에서 재사용한다.
- 후보 생성 입력은 `issue_docent.term_spans[*].term`만 사용한다. `sentence`는 본문 위치/맥락 참고용으로 남기되 dictionary 중복 판단 키로 쓰지 않는다.
- 정의와 예시는 Google Vertex AI를 호출해 생성한다. 모델은 기존 Dictionary 생성 코드에서 사용하던 동일한 Vertex AI 모델 설정을 재사용한다.
- 생성 문체는 주린이가 이해하기 쉬운 설명을 기준으로 하며, 설명 안에 또 다른 어려운 금융 용어를 늘어놓지 않는다.

기존 `9990-jangdokdae/dictionary` 구현 기준:

- 구현 구조는 LangChain + LangGraph 기반 파이프라인을 유지한다.
- 모델 호출은 LangChain의 chat model 래퍼를 통해 수행한다.
- 구현 기본 모델명은 `gemini-3-flash-preview`, fallback/cost 모델명은 `gemini-3.1-flash-lite-preview`다.
- 실제 호출 전 `.env`의 `DICTIONARY_MODEL`, `DICTIONARY_FALLBACK_MODEL` 값을 우선 확인한다.
- 서버 구현에서는 `jangdokdae-server`의 `uv.lock`에 이미 포함된 LangChain/LangGraph 계열 의존성을 우선 사용한다. 불필요한 새 LLM 프레임워크는 추가하지 않는다.

## 6. API

```http
GET /api/v1/dictionary?query=&type=&status=
GET /api/v1/dictionary/{term}
POST /api/v1/dictionary/candidates/from-issue/{issue_id}
```

### `GET /api/v1/dictionary`

목록/검색 API.

```ts
interface DictionaryTermResponse {
  id: number;
  term: string;
  term_type: "finance" | "domain";
  definition: string;
  example: string | null;
  status: "candidate" | "approved" | "rejected";
}
```

### `GET /api/v1/dictionary/{term}`

Issue Detail tooltip에서 단건 조회할 수 있다.

- `approved`가 있으면 200.
- 후보만 있으면 200으로 주되 `status="candidate"`를 포함한다.
- 없으면 404 또는 `"준비 중인 용어입니다."` fallback 중 하나를 프론트 정책으로 정한다.

### `POST /api/v1/dictionary/candidates/from-issue/{issue_id}`

특정 `issue_docent`의 `term_spans`를 기준으로 후보를 생성한다.

- 현재는 수동 후보 생성 API로 구현한다.
- 운영 자동 호출은 파이프라인 후속 노드 또는 백필 스크립트로 추가한다.

## 7. 파이프라인 연결 위치

정석은 `issue_docent` 생성 후 별도 후처리로 붙인다.

```text
fetch → classify → enrich → generate issue_docent → extract dictionary candidates
```

이유:

- 콘텐츠 생성과 사전 후보 생성의 실패 단위를 분리한다.
- 사전 생성 실패가 이슈 발행을 막지 않는다.
- 이미 생성된 `issue_docent`에 대해 백필하기 쉽다.

## 8. 이번 범위에서 하지 않는 것

- 관계형 관련 이슈 테이블.
- 용어 alias/disambiguation.
- 사용자별 학습 완료/북마크.
- Dictionary 승인 관리자 화면/API.
- 기존 dictionary 레포 import.

## 9. 결정 필요

DB 변경 전에 아래를 확정해야 한다.

1. `dictionary_terms.term`을 전역 unique로 둘지, `term + term_type` unique로 둘지.
2. 후보 생성은 API로 열지 script만 둘지.
3. `candidate` 용어를 사용자에게 보여줄지, `approved`만 보여줄지.

추천:

- 1차는 `term` 전역 unique.
- 후보 생성은 script 먼저.
- 사용자 화면은 `approved` 우선, 없으면 fallback 문구.
