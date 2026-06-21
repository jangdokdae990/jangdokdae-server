# 단독 실행: uv run pytest tests/test_article_fetcher.py -s
"""article_fetcher 회귀 테스트 — 본문 fetch가 http→https 301을 따라가는지 검증 (설계 02 §8.4).

배경: 국내 다수 매체가 http→https 301을 반환한다. 추적하지 않으면 fetch가 빈 리다이렉트
페이지를 받아 본문 추출에 실패한다(노션 todo "본문 fetch 품질" 항목, 커밋 bb8b610에서 수정).
이 테스트는 두 코드 경로(fetch_article_body의 1회용 클라이언트 · fetch_first_available의
재사용 클라이언트)가 각자 follow_redirects=True로 클라이언트를 만드는지를 회귀 방지로 고정한다.

검증 방식: 클라이언트를 주입하면 함수가 만드는 클라이언트 설정을 우회하므로 주입하지 않는다.
대신 httpx.AsyncClient에 MockTransport를 끼워 네트워크만 가로챈다 — 리다이렉트 추적은
transport가 아니라 클라이언트 계층이 담당하므로 follow_redirects 설정이 그대로 시험된다.
follow_redirects가 빠지면 301 본문(빈 페이지)이 추출되어 None이 되고 테스트가 실패한다.
"""

import httpx
import pytest

from services.analyzer import article_fetcher
from services.analyzer.article_fetcher import _extract_body

REDIRECT_URL = "http://news.example.com/article"  # 매체가 https로 301 보내는 원본 URL
FINAL_URL = "https://news.example.com/article"
# 최종(https) 페이지에만 있는 마커 — 301 페이지에는 없어 리다이렉트 추적 여부를 구분한다.
ARTICLE_MARKER = "ARTICLE_BODY_MARKER"
EXTRACTED_BODY = "삼성전자 3분기 실적 본문. " * 30  # MIN_BODY_LENGTH(200) 초과
ARTICLE_HTML = f"<html><body><article>{ARTICLE_MARKER}</article></body></html>"


def _redirect_handler(request: httpx.Request) -> httpx.Response:
    """http는 빈 본문으로 301, https는 마커가 든 기사 HTML로 200."""
    if request.url.scheme == "http":
        return httpx.Response(301, headers={"Location": FINAL_URL})
    return httpx.Response(200, html=ARTICLE_HTML)


def _paywall_then_article_handler(request: httpx.Request) -> httpx.Response:
    """첫 후보는 페이월(짧은 본문), 두 번째 후보는 정상 기사."""
    if request.url.path == "/paywall":
        return httpx.Response(200, html="<html><body><p>로그인 후 보기</p></body></html>")
    return httpx.Response(200, html=ARTICLE_HTML)


@pytest.fixture
def patched_fetch(monkeypatch):
    """httpx.AsyncClient에 MockTransport를 주입하고 trafilatura.extract를 가짜로 대체한다.

    가짜 extract는 마커가 있을 때만 본문을 반환 — 301 빈 페이지가 추출되면 None이 되어,
    follow_redirects 회귀 시 테스트가 실패하도록 한다.
    """

    def install_handler(handler):
        real_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(article_fetcher.httpx, "AsyncClient", factory)

    def fake_extract(html, *args, **kwargs):
        return EXTRACTED_BODY if ARTICLE_MARKER in (html or "") else None

    monkeypatch.setattr(article_fetcher.trafilatura, "extract", fake_extract)
    return install_handler


async def test_fetch_article_body_follows_http_to_https_redirect(patched_fetch):
    """1회용 클라이언트 경로: http URL이 https로 301돼도 본문을 추출한다."""
    patched_fetch(_redirect_handler)

    body = await article_fetcher.fetch_article_body(REDIRECT_URL)

    assert body == EXTRACTED_BODY


async def test_fetch_first_available_follows_redirect(patched_fetch):
    """재사용 클라이언트 경로: fetch_first_available도 301을 추적한다."""
    patched_fetch(_redirect_handler)

    body = await article_fetcher.fetch_first_available([REDIRECT_URL])

    assert body == EXTRACTED_BODY


async def test_fetch_first_available_falls_back_past_paywall(patched_fetch):
    """첫 후보가 페이월(과소 추출)이면 다음 후보로 넘어가 본문을 반환한다."""
    patched_fetch(_paywall_then_article_handler)

    body = await article_fetcher.fetch_first_available(
        ["https://news.example.com/paywall", "https://news.example.com/article"]
    )

    assert body == EXTRACTED_BODY


# favor_precision은 단조 반복 텍스트를 저품질로 버리므로, 실제 기사처럼 문단을 변주한다.
_REAL_PARAS = "".join(
    f"<p>실제 기자가 작성한 기사 본문 {i}번째 문단으로, 사건의 경위와 배경을 구체적으로 전한다.</p>"
    for i in range(8)
)
_AI_PARAS = "".join(
    f"<p>AI 자동 생성 분석 위젯이 만든 {i}번째 요약 문장으로 본문과 무관한 합성 텍스트다.</p>"
    for i in range(8)
)


def test_extract_body_prefers_article_body_over_ai_widget():
    """itemprop=articleBody가 있으면 그 안만 추출 — AI 위젯 등 잡음을 구조적으로 배제한다."""
    html = (
        f'<html><body><div class="ai_explain">{_AI_PARAS}</div>'
        f'<div itemprop="articleBody">{_REAL_PARAS}</div></body></html>'
    )

    body = _extract_body(html)

    assert body is not None
    assert "실제 기자가 작성한" in body
    assert "AI 자동 생성 분석" not in body


def test_extract_body_falls_back_without_article_body_container():
    """itemprop=articleBody가 없으면 전체 HTML에서 추출한다(폴백)."""
    html = f"<html><body><article>{_REAL_PARAS}</article></body></html>"

    body = _extract_body(html)

    assert body is not None
    assert "실제 기자가 작성한" in body


def test_extract_body_concatenates_multiple_article_body_nodes():
    """itemprop=articleBody가 여러 개면 모두 이어 붙여 추출한다(본문 분할 기사 보존)."""
    first = "".join(
        f"<p>첫째 블록 {i}번째 문단으로, 사건의 경위와 배경을 구체적으로 전한다.</p>"
        for i in range(4)
    )
    second = "".join(
        f"<p>둘째 블록 {i}번째 문단으로, 향후 전망과 시장 반응을 상세히 설명한다.</p>"
        for i in range(4)
    )
    html = (
        f'<html><body><div itemprop="articleBody">{first}</div>'
        f'<p>중간 위젯</p>'
        f'<div itemprop="articleBody">{second}</div></body></html>'
    )

    body = _extract_body(html)

    assert body is not None
    assert "첫째 블록" in body
    assert "둘째 블록" in body


def test_extract_body_falls_back_when_container_extraction_empty():
    """articleBody 컨테이너가 비어 추출 결과가 없으면 전체 HTML로 폴백한다(기사 누락 방지)."""
    html = (
        f'<html><body><div itemprop="articleBody"></div>'
        f'<article>{_REAL_PARAS}</article></body></html>'
    )

    body = _extract_body(html)

    assert body is not None
    assert "실제 기자가 작성한" in body
