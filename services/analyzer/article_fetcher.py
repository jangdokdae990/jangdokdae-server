"""본문 fetch — 분석 단계가 대표 기사 본문만 실시간 추출 후 폐기하는 도구.

설계 02 §3.4·§8.4. snippet·본문은 DB에 저장하지 않는다(저작권 리스크). 분석 단계가
클러스터 대표기사 URL로 trafilatura를 통해 본문을 fetch해 LLM 입력으로 쓰고 즉시 폐기한다.
본문 fetch는 단일 단계(분석) 전용이라 공유 tools/가 아니라 소비자(analyzer) 옆에 둔다(설계 01 §4).

전략(설계 02 §8.4):
    정상 fetch → 본문 반환 / 페이월·추출 실패 → member_news_ids 중심 근접순(→05 §5.8)
    다음 후보 순차 시도 / 전부 실패 → None(호출부가 title만으로 분석).
"""

import asyncio
import logging
from collections.abc import Iterable

import httpx
import trafilatura

from services.collector.tools.with_retry import with_retry
from utils.http import USER_AGENT

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
# 추출 본문이 이보다 짧으면 페이월·추출 실패로 보고 다음 후보로 넘어간다.
# 정상 기사 본문은 수백 자 이상이므로, 미리보기 한두 문장만 남는 페이월을 걸러낸다.
MIN_BODY_LENGTH = 200


# 일시 오류(타임아웃·커넥션)만 재시도한다 — TransportError가 TimeoutException·NetworkError를
# 모두 포함. 페이월·삭제(4xx)는 raise_for_status가 HTTPStatusError를 올리며 retry_on에 없어
# 즉시 다음 후보로 넘어간다(무의미한 백오프 회피).
@with_retry(max_attempts=2, retry_on=httpx.TransportError)
async def _download(client: httpx.AsyncClient, url: str) -> str:
    """외부 HTML을 받아 본문 텍스트를 반환. 일시 오류만 1회 더 시도한다."""
    response = await client.get(url)
    response.raise_for_status()
    return response.text


async def fetch_article_body(
    url: str, *, client: httpx.AsyncClient | None = None, timeout: float = DEFAULT_TIMEOUT
) -> str | None:
    """단일 URL의 본문을 추출해 반환. 다운로드 실패·페이월·과소 추출 시 None.

    client를 주입하면 여러 후보 fetch에서 커넥션을 재사용한다(미주입 시 1회용 생성·정리).
    """
    owns_client = client is None
    if client is None:
        # follow_redirects 필수 — 국내 다수 매체가 http→https 301을 반환해, 추적하지 않으면
        # raise_for_status가 3xx에서 실패한다(실험2에서 확인: 추적 시 fetch 성공률 92%).
        client = httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
    try:
        html = await _download(client, url)
    except httpx.HTTPError as exc:
        logger.warning("본문 fetch 실패 url=%s err=%s", url, exc)
        return None
    finally:
        if owns_client:
            await client.aclose()

    # trafilatura.extract는 동기 CPU 작업 — 이벤트 루프 블로킹 방지로 스레드에 오프로드.
    body = await asyncio.to_thread(trafilatura.extract, html)
    if not body or len(body) < MIN_BODY_LENGTH:
        logger.info("본문 추출 부족(페이월 가능) url=%s len=%d", url, len(body or ""))
        return None
    return body


async def fetch_first_available(
    urls: Iterable[str], *, timeout: float = DEFAULT_TIMEOUT
) -> str | None:
    """후보 URL을 중심 근접순대로 시도해 첫 성공 본문을 반환. 전부 실패 시 None."""
    headers = {"User-Agent": USER_AGENT}
    # follow_redirects — fetch_article_body의 1회용 클라이언트와 같은 이유(http→https 301).
    async with httpx.AsyncClient(
        timeout=timeout, headers=headers, follow_redirects=True
    ) as client:
        for url in urls:
            body = await fetch_article_body(url, client=client)
            if body is not None:
                return body
    logger.info("모든 후보 본문 fetch 실패 — title만으로 분석")
    return None
