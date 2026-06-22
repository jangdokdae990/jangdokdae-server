"""대표 기사 본문을 실시간으로 추출하는 도구.

trafilatura로 기사 URL의 본문을 fetch해 LLM 입력으로 쓰고, DB에는 저장하지 않는다(저작권).
추출 실패·페이월이면 다음 후보 URL을 시도하고, 전부 실패하면 None을 반환한다.
"""

import asyncio
import logging
from collections.abc import Iterable

import httpx
import trafilatura
from lxml import html as lxml_html
from lxml.etree import LxmlError

from services.collector.tools.with_retry import with_retry
from utils.http import USER_AGENT

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
# 추출 본문이 이보다 짧으면 페이월·추출 실패로 보고 다음 후보로 넘어간다.
MIN_BODY_LENGTH = 200


def _extract_body(html_text: str) -> str | None:
    """HTML에서 기자 작성 기사 본문만 추출한다.

    schema.org `itemprop="articleBody"` 컨테이너가 있으면 **그 안만** 추출한다 — 글자크기·
    시세(증권정보)·관련기사·AI 자동요약 등 본문 밖 위젯을 구조 단계에서 배제하기 위함이다.
    컨테이너가 여러 개면 모두 이어 붙여 추출한다(본문이 여러 블록으로 쪼개진 기사 보존).

    컨테이너 추출 결과가 비면(favor_precision이 짧은 단편을 버리는 경우 등) 기사 누락을 막기
    위해 전체 HTML에서 재추출한다 — 본문 밖 위젯이 섞이더라도 본문이 통째로 사라지는 것보다 낫다.
    컨테이너가 아예 없을 때도 전체 HTML에서 추출한다.

    `favor_precision`으로 정밀도를 높여(경계의 페이지 잡음 제거) 짧은 본문도 안정적으로 뽑는다.
    """
    try:
        doc = lxml_html.fromstring(html_text)
        nodes = doc.xpath('//*[@itemprop="articleBody"]')
    except (LxmlError, ValueError):
        nodes = []
    if nodes:
        fragment = "\n".join(
            lxml_html.tostring(node, encoding="unicode") for node in nodes
        )
        body = trafilatura.extract(fragment, favor_precision=True)
        if body:
            return body
    return trafilatura.extract(html_text, favor_precision=True)


def _make_client(timeout: float) -> httpx.AsyncClient:
    """본문 fetch용 httpx 클라이언트. http→https 301을 추적하려면 follow_redirects가 필수."""
    return httpx.AsyncClient(
        timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    )


# 일시 오류(타임아웃·커넥션)만 재시도하고, 페이월·삭제(4xx)는 재시도 없이 다음 후보로 넘긴다.
@with_retry(max_attempts=2, retry_on=httpx.TransportError)
async def _download(client: httpx.AsyncClient, url: str) -> str:
    """외부 HTML을 받아 본문 텍스트를 반환한다."""
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
        client = _make_client(timeout)
    try:
        html = await _download(client, url)
    except httpx.HTTPError as exc:
        logger.warning("본문 fetch 실패 url=%s err=%s", url, exc)
        return None
    finally:
        if owns_client:
            await client.aclose()

    # _extract_body(lxml+trafilatura)는 동기 CPU 작업 — 이벤트 루프 블로킹 방지로 스레드 오프로드.
    body = await asyncio.to_thread(_extract_body, html)
    if not body or len(body) < MIN_BODY_LENGTH:
        logger.info("본문 추출 부족(페이월 가능) url=%s len=%d", url, len(body or ""))
        return None
    return body


async def fetch_first_available(
    urls: Iterable[str], *, timeout: float = DEFAULT_TIMEOUT
) -> str | None:
    """후보 URL을 순서대로 시도해 첫 성공 본문을 반환한다. 전부 실패 시 None."""
    async with _make_client(timeout) as client:
        for url in urls:
            body = await fetch_article_body(url, client=client)
            if body is not None:
                return body
    logger.info("모든 후보 본문 fetch 실패 — title만으로 분석")
    return None
