"""로그 유출 방지 — 외부 API 키가 URL/쿼리에 실려 예외 메시지로 새는 것을 차단한다."""

from app.config import settings


def redact_secrets(value: object) -> str:
    """문자열로 변환 후 알려진 API 키 값을 '***'로 마스킹한다.

    DART는 crtfc_key 쿼리, ECOS는 URL 경로에 키가 실린다. httpx 예외 메시지에는
    요청 URL 전체가 포함되므로, 예외를 그대로 로깅하면 키가 평문으로 남는다.
    수집기의 예외 로깅은 이 함수로 감싸야 한다.
    """
    text = str(value)
    # 빈 키를 replace하면 모든 위치에 '***'가 끼므로 반드시 건너뛴다.
    for secret in (settings.opendart_api_key, settings.ecos_api_key):
        if secret:
            text = text.replace(secret, "***")
    return text
