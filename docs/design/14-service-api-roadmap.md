# 14. 서비스 API 확장 로드맵

이 문서는 v2 프론트 화면을 실제 API로 전환할 때의 우선순위를 정리한다.

기준:

- 기존 DB schema를 최대한 유지한다.
- 화면별 mock data를 한 번에 제거하지 않는다.
- 저장소가 없는 기능은 API보다 schema 설계를 먼저 한다.

## 1. 현재 DB/API로 바로 가능한 범위

| 화면 | 1차 API | 기준 테이블 | 비고 |
| --- | --- | --- | --- |
| Issues Explore | `GET /api/v1/issues` | `issue_docent`, `news_cluster`, `news_analysis` | `q`, `sort`, `market`, `sector_id`, `company_id` |
| Issue Detail | `GET /api/v1/issues/{id}` | `issue_docent`, `news_cluster`, `news` | reader cards, source articles, term fallback |
| Onboarding | `GET /markets`, `/sectors`, `/companies`, `POST /onboarding/interests` | `markets`, `sectors`, `company_entities`, user interest tables | FE state를 id 기반으로 바꿔야 함 |
| Login/Auth | OAuth, `/auth/me`, `/auth/logout` | `users` | httpOnly cookie 기준 |
| My Page | `/user/profile` | `users`, user interest tables | 읽은 이슈/퀴즈/저장은 아직 mock |

## 2. 1차 구현 순서

### P0. Issue API 정착

완료 또는 PR 중:

- `GET /api/v1/issues`
- `GET /api/v1/issues/{id}`
- issue list filter/sort

남은 보정:

- `term_spans`의 사용 문장 보존 여부.
- source article 순서와 빈 URL 방어.
- thumbnail URL이 없는 동안 FE fallback 유지.

### P1. Onboarding API 연동

해야 할 일:

- FE `selectedMarkets/selectedSectors/selectedStocks`를 name 배열에서 id 기반으로 전환.
- master API 응답을 display model로 변환.
- `POST /api/v1/onboarding/interests`에 id 배열 제출.
- `/auth/me` 또는 `/user/profile`에서 관심 설정 복원.

주의:

- 마이그레이션은 필요 없다.
- UI 라벨은 `name_ko`를 사용하되 FE 내부 저장은 id를 기준으로 한다.

### P2. My Page profile/interests 연동

해야 할 일:

- `/user/profile`로 사용자 기본 정보와 관심 id를 가져온다.
- id를 master API 결과와 매칭해 라벨로 표시한다.

후순위:

- 읽은 이슈 수.
- 퀴즈 기록.
- 저장한 이슈.

이 세 가지는 아직 테이블이 없다.

### P3. Home API 연동

해야 할 일:

- 별도 Home API를 만들지 않고 `GET /api/v1/issues?sort=importance&limit=...`를 재사용한다.
- ticker도 title/teaser 기반으로 먼저 구성한다.

후순위:

- 사용자 관심 기반 섹션은 onboarding/auth 연동 후 구현한다.
- AI thumbnail은 asset 저장소 설계 후 붙인다.

## 3. Schema가 필요한 범위

| 기능 | 필요한 저장소 | 우선순위 |
| --- | --- | --- |
| Dictionary | `dictionary_terms` | P0 진행 |
| Quiz | `issue_docent.quizzes` | P1 진행 |
| Quiz result | `quiz_results` | 후속 |
| Bookmark | `issue_bookmarks` | P6 |
| Read activity | `issue_reads` | P6 |
| Search suggestions | 별도 저장소 없이 query 조합 가능 | P7 |
| AI thumbnail | `issue_assets` 또는 `generated_assets` | P7 |

## 4. Dictionary 우선 설계

`term_spans`가 이미 있으므로 Dictionary는 다음으로 설계하기 좋다.

권장 결정:

- `dictionary_terms.term` 전역 unique.
- 후보 생성은 `POST /api/v1/dictionary/candidates/from-issue/{issue_id}` 먼저.
- 사용자 화면은 `approved` 우선, 없으면 fallback.

## 5. 1차에서 유지할 mock

| 화면 | 유지할 mock | 이유 |
| --- | --- | --- |
| Quiz | 문항/정답/결과 | 테이블 없음 |
| My Page | stats, read history, quiz history | 테이블 없음 |
| Home | 개인화 관심 이슈 | auth/onboarding 연동 이후 |
| Dictionary | 검수/승인된 용어가 부족한 경우 기존 mock fallback | 초기 데이터 부족 |
| Issue thumbnails | AI 이미지 | asset 저장소 없음 |

## 6. 다음 PR 추천 순서

1. Onboarding FE id 기반 전환 + master API 연동.
2. My Page profile/interests API 연동.
3. Home issue list API 연동.
4. Dictionary 백필 script와 승인 플로우.
5. Quiz schema/API.

## 7. 현재 완전 구현 목표

우선순위는 Dictionary → Quiz → Onboarding → My Page → Home이다.

- Dictionary: `term_spans[*].term` 추출·중복 제거 → LangChain+LangGraph+Vertex AI(`gemini-3-flash-preview` 계열)로 설명/예시 생성 → `dictionary_terms(status=candidate)` 적재 → API/프론트 툴팁 연결.
- Quiz: 기존 v1 LangGraph 흐름을 유지하고 `term`/`issue`/`domain` 3문항 고정으로 확장한다. 저장소는 별도 `quizzes` 테이블이 아니라 `issue_docent.quizzes` JSONB다. 기존 데이터는 quiz-only 백필한다.
- 운영 DB 마이그레이션은 코드 검증 후 별도 단계로 `alembic current` 확인 → `alembic upgrade head` → 스모크 테스트 순서로 적용한다.
