# 쿠키 · 세션 보안 규정

> **작성자** Kim minkyoung · **작성일** 2026-06-21 · **범위** httpOnly 쿠키 + stateless JWT 세션의 보안 규정·운영 체크리스트·설계 트레이드오프

## 목차

1. [세션 모델 개요](#1-세션-모델-개요)
2. [쿠키 속성 규정](#2-쿠키-속성-규정)
3. [세션 토큰(JWT) 규정](#3-세션-토큰jwt-규정)
4. [CSRF 방어 규정](#4-csrf-방어-규정)
5. [비밀·전송 관리 규정](#5-비밀전송-관리-규정)
6. [운영 배포 체크리스트](#6-운영-배포-체크리스트)
7. [알려진 갭과 설계 트레이드오프](#7-알려진-갭과-설계-트레이드오프)
8. [참고 자료](#8-참고-자료)

---

## 1. 세션 모델 개요

장독대 인증은 **BE 전담 OAuth 토큰 교환 + httpOnly 쿠키 + stateless JWT** 모델이다.

- FE는 토큰을 직접 다루지 않는다(httpOnly 쿠키 → JS 접근 불가).
- 세션 상태를 서버에 저장하지 않는다(stateless). access는 단명, refresh로 갱신·회전한다.
- client secret·서명 키는 BE 환경변수로만 보관한다.

구현 위치: `app/core/security.py`(발급·검증·쿠키), `app/api/routers/auth.py`(흐름·CSRF), `app/config.py`(설정).

---

## 2. 쿠키 속성 규정

인증 쿠키(access·refresh)와 state 쿠키는 아래 속성을 따른다.

| 속성 | 규정 | 설정 출처 | 이유 |
|------|------|-----------|------|
| HttpOnly | 인증 쿠키 필수 설정 | 코드 고정 `True` | JS의 `document.cookie` 접근 차단 → XSS 토큰 탈취 방지 |
| Secure | 운영(HTTPS) 필수 설정 | `COOKIE_SECURE` | 평문(HTTP)에서 쿠키 미전송 → 중간자 가로채기 방지 |
| SameSite | `Lax` 이상 | `COOKIE_SAMESITE` | CSRF 1차 방어. OAuth top-level redirect 쿠키 전달 위해 Strict 대신 Lax |
| Path | 범위 최소화(`/`) | 코드 | |
| Domain | 와일드카드 지양 | `COOKIE_DOMAIN` | 서브도메인 과다 노출 방지 |
| Max-Age | 짧게 — access 30분 · refresh 14일 · state 5분 | `*_EXPIRE_*` | 노출 시 피해 창 축소 |

**핵심 규정**: 운영 배포 시 `COOKIE_SECURE=True` 필수. 로컬 기본값은 `False`(HTTP 개발)이므로 HTTPS 환경에서 반드시 전환한다.

---

## 3. 세션 토큰(JWT) 규정

- **서명 키**: `SECRET_KEY`는 코드 하드코딩 금지·`.env`로만 관리(필수 필드, 기본값 없음). 고엔트로피 권장(`openssl rand -hex 32`).
- **만료(exp) 필수**: 모든 토큰에 `exp` 포함 → 무기한 유효 토큰 금지.
- **용도 분리**: `type`(access/refresh) 클레임으로 혼용 차단 — refresh를 access로 쓰지 못한다.
- **알고리즘 고정**: 검증 시 허용 알고리즘을 명시(`algorithms=[ALGORITHM]`) → `alg:none`·알고리즘 혼동 공격 차단.
- **단명 access + 장수명 refresh**: access 30분, refresh로 갱신.
- **refresh 회전**: 갱신 시 access·refresh를 동시 재발급해 재사용 창을 축소.

---

## 4. CSRF 방어 규정

- **OAuth state**: `/login`에서 고엔트로피 state(`secrets.token_urlsafe`)를 발급해 짧은 수명 쿠키로 저장하고, `/callback`에서 쿼리 state와 대조한다(CSRF·인가코드 가로채기 방지). 콜백 성공 시 state 쿠키를 삭제한다.
- **SameSite=Lax**: 쿠키 기반 인증의 CSRF 1차 방어.
- **상태변경 API**: SameSite는 1차 방어일 뿐이다. 상태변경(예: 온보딩 제출·로그아웃)에는 별도 CSRF 토큰(double-submit) 도입을 검토한다. (현재 미구현 — §7)

---

## 5. 비밀·전송 관리 규정

- client secret·`SECRET_KEY`는 **BE 환경변수로만** 둔다. FE 번들 유입 금지(FE는 `NEXT_PUBLIC_*` 노출 가능 값만).
- `.env`·시크릿·키는 절대 커밋하지 않는다(`.gitignore`로 차단, `.env.example`만 공유).
- 토큰을 FE의 localStorage에 저장하지 않는다(httpOnly 쿠키로 대체) → XSS 노출면 축소.

---

## 6. 운영 배포 체크리스트

- [ ] `COOKIE_SECURE=True` (HTTPS 전제)
- [ ] `SECRET_KEY` 고엔트로피 값으로 교체(개발용 placeholder 금지)
- [ ] `COOKIE_DOMAIN` 운영 도메인으로 지정(예: `.jangdokdae.com`)
- [ ] `COOKIE_SAMESITE` 정책 확인(기본 `lax`)
- [ ] `CORS_ORIGINS`를 운영 FE origin으로 제한(와일드카드 금지, `allow_credentials=True`와 `*` 병용 불가)
- [ ] OAuth redirect URI를 provider 콘솔 등록값과 일치(운영 도메인)

---

## 7. 알려진 갭과 설계 트레이드오프

stateless JWT를 택한 결과 의도적으로 비워 둔 항목이다(서버 세션 미저장 = 단순·확장 용이 ↔ 즉시 무효화·재사용 탐지 약함).

- **CSRF 토큰 미구현**: 상태변경 API는 현재 SameSite=Lax에만 의존. double-submit 토큰 도입 검토 대상.
- **로그아웃이 stateless**: `/logout`은 쿠키만 삭제한다. 이미 발급된 access는 만료(최대 30분)까지 유효 → 즉시 무효화하려면 서버 측 deny-list 필요.
- **refresh 재사용 탐지 없음**: 회전은 하지만 탈취된 옛 refresh 재사용 탐지(reuse detection)는 서버 저장 없이는 한계.
- **state 쿠키 cleanup**: 콜백 성공 시 삭제하나, 실패·이탈 시 5분 max-age 자연 만료에 의존.

보안을 더 끌어올릴 경우 위 항목을 우선순위로 다룬다.

---

## 8. 참고 자료

- OWASP Cheat Sheet — Session Management <https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html>
- OWASP Cheat Sheet — Cross-Site Request Forgery Prevention <https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html>
- MDN — Set-Cookie <https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie>
- [`.env.example`](../../.env.example) — 쿠키·JWT·OAuth 환경 변수
- [`docs/API_SPEC.md`](../API_SPEC.md) — 인증 엔드포인트 계약
