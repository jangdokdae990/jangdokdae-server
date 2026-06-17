"""외부 API 일시 실패용 지수 백오프 재시도 데코레이터.

수집기의 외부 호출(`_fetch` 등)에 붙여 일시적 네트워크 오류·5xx를 한두 번 더
시도해 흡수한다. 재시도 로그는 redact로 감싸 키 유출을 막는다.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import ParamSpec, TypeVar

from services.collector.tools.redact import redact_secrets

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

# 백오프 밑(base). 대기 = _BACKOFF_BASE ** attempt → 1s → 2s → 4s …
_BACKOFF_BASE = 2


def with_retry(
    max_attempts: int = 3,
    retry_on: type[Exception] | tuple[type[Exception], ...] = Exception,
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """async 함수를 지수 백오프로 최대 max_attempts회 재시도하는 데코레이터.

    retry_on에 해당하는 예외만 재시도한다(기본값 Exception=전부). 마지막 시도까지
    실패하거나 retry_on에 없는 예외는 그대로 올린다. 재시도 전 경고 로그를 남기되
    예외 메시지는 redact_secrets로 마스킹한다.
    """

    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except retry_on as exc:
                    if attempt == max_attempts - 1:
                        raise
                    delay = _BACKOFF_BASE**attempt
                    logger.warning(
                        "%s 실패(시도 %d/%d), %ds 후 재시도: %s",
                        func.__name__,
                        attempt + 1,
                        max_attempts,
                        delay,
                        redact_secrets(exc),
                    )
                    await asyncio.sleep(delay)
            # 도달 불가: 위 루프는 항상 return 또는 raise로 빠져나간다.
            raise AssertionError("with_retry: 루프가 결과 없이 종료됨")

        return wrapper

    return decorator
