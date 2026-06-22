# 장독대 API 명세

> **작성자** Kim minkyoung · **작성일** 2026-06-21 · **범위** 인증(OAuth 카카오·구글)·온보딩·마스터 조회 API 계약

## 목차

1. [공통 규약](#1-공통-규약)
2. [인증 — OAuth 로그인](#2-인증--oauth-로그인)
3. [인증 — 세션 관리](#3-인증--세션-관리)
4. [마스터 조회 (온보딩 1~3단계)](#4-마스터-조회-온보딩-13단계)
5. [온보딩 제출 · 마이페이지](#5-온보딩-제출--마이페이지)

---

## 1. 공통 규약

- **Base path**: 모든 엔드포인트는 `/api/v1` 접두사를 가진다.
- **세션**: BE가 OAuth 토큰 교환을 전담하고, 세션은 **httpOnly 쿠키 + stateless JWT**로 유지한다. FE는 토큰을 직접 다루지 않는다.
- **인증 구분**: 보호 라우터는 access 쿠키 필수(`get_current_user`), 공개 라우터(마스터 조회)는 비로그인 허용(`get_current_user_optional`).
- **에러 응답 봉투**: 모든 에러는 아래 형태로 통일한다.

```json
{ "error": { "code": "unauthorized", "message": "로그인이 필요합니다" } }
```

---

## 2. 인증 — OAuth 로그인

`{provider}`는 `kakao` | `google`. redirect URI는 provider 콘솔에 `{backend}/api/v1/auth/{provider}/callback`로 등록한다.

| 메서드 | 경로 | 설명 | 인증 |
|--------|------|------|------|
| GET | `/api/v1/auth/{provider}/login` | state(CSRF) 발급 후 provider authorize로 302 redirect | 불필요 |
| GET | `/api/v1/auth/{provider}/callback` | state 검증 → code→token → userinfo 정규화 → User upsert → JWT 쿠키 발급 → FE로 redirect | 불필요 |
| GET | `/api/v1/auth/me` | 현재 사용자 + 온보딩 완료 여부 + 관심 요약 | access 쿠키 |

- 콜백 완료 후 redirect 대상: 신규/온보딩 미완료는 온보딩 경로, 기존 사용자는 홈(`FRONTEND_BASE_URL`).
- `userinfo` 정규화 필드: `provider`, `provider_user_id`, `email`, `nickname`, `profile_image`.
- `/auth/me` 응답에 `is_new_user` 또는 `onboarding_completed` 플래그 포함.

---

## 3. 인증 — 세션 관리

| 메서드 | 경로 | 설명 | 인증 |
|--------|------|------|------|
| POST | `/api/v1/auth/refresh` | refresh 쿠키 검증 후 access 재발급(stateless) | refresh 쿠키 |
| POST | `/api/v1/auth/logout` | 세션 쿠키(access·refresh) 무효화 | access 쿠키 |

---

## 4. 마스터 조회 (온보딩 1~3단계)

모두 읽기 전용이라 guest 허용(`get_current_user_optional`).

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/v1/markets` | 활성 시장 목록 |
| GET | `/api/v1/sectors` | 섹터 마스터 목록 |
| GET | `/api/v1/companies` | 활성 종목 조회 |

종목 쿼리 파라미터: `sector`(섹터 id), `market`(시장 코드 — `KR`→KOSPI/KOSDAQ), `q`(종목명·코드 검색), `limit`(1~100, 기본 20), `cursor`(직전 페이지 마지막 id). 응답은 `{ items: [...], next_cursor }` 커서 페이지로, `next_cursor`가 null이면 마지막 페이지.

---

## 5. 온보딩 제출 · 마이페이지

| 메서드 | 경로 | 설명 | 인증 |
|--------|------|------|------|
| POST | `/api/v1/onboarding/interests` | 관심 시장·섹터(필수, 빈 배열 차단)·종목(옵션) 제출 → 멱등 대체 + 온보딩 완료 갱신 | access 쿠키 |
| GET | `/api/v1/user/profile` | 사용자 + 관심(시장/섹터/종목) + 온보딩 상태 | access 쿠키 |

- 제출 시 시장·섹터·종목 id의 존재·활성을 검증한다(불일치 → 422).
- 관심 수정은 별도 API 없이 온보딩 제출 API를 재사용한다.
- 투자 성향 결과(5단계)는 투자 성향 테스트(노션 §9, 보류) 구현 후 프로필에 추가 예정.

---

## 참고 자료

- [`docs/rules/architecture.md`](rules/architecture.md) — 레이어·폴더 구조
- [`docs/rules/conventions.md`](rules/conventions.md) — 파일·함수 네이밍 규칙
- [`.env.example`](../.env.example) — OAuth·쿠키·JWT 환경 변수
