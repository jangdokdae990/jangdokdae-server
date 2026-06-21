# 단독 실행: uv run pytest tests/test_financial_collector.py -s
"""FinancialCollector 회귀 테스트 — fs_div(CFS/OFS) 출처 보존 · 일시 오류 재시도.

배경(노션 todo 03):
- (fs_div) 연결재무제표(CFS) 우선·개별(OFS) 폴백으로 수치를 집을 때, 실제로 어느
  재무제표에서 취했는지를 `fs_div`로 보존해 연도 간 비교 시 출처를 추적할 수 있는지.
- (재시도) `_fetch_accounts`가 일시 네트워크 오류(TransportError)를 with_retry로 한 번
  더 시도해 흡수하는지(4xx/5xx·status=013은 재시도 대상 아님).

검증 방식: FinancialCollector가 만드는 httpx.AsyncClient에 MockTransport를 끼워
네트워크만 가로챈다(test_rss_collector와 동일 패턴).
"""

import httpx
import pytest

from services.collector import financial_collector
from services.collector.financial_collector import FinancialCollector
from services.collector.stock_symbols import StockSymbol

COMPANY = StockSymbol("005930", "삼성전자", "00126380")

# DART fnlttSinglAcntAll.json 정상 응답 — 손익(IS)·재무상태(BS) 핵심 계정
_FS_OK = {
    "status": "000",
    "message": "정상",
    "list": [
        {"sj_div": "IS", "account_nm": "매출액", "thstrm_amount": "1,000", "rcept_no": "20260101000001"},  # noqa: E501
        {"sj_div": "BS", "account_nm": "자산총계", "thstrm_amount": "5,000", "rcept_no": "20260101000001"},  # noqa: E501
    ],
}
# 데이터 없음(정상 종료) — CFS 미작성 기업의 연결재무제표 조회 결과
_FS_EMPTY = {"status": "013", "message": "조회된 데이터가 없습니다."}


@pytest.fixture
def install_transport(monkeypatch):
    """FinancialCollector가 만드는 httpx.AsyncClient에 MockTransport를 끼운다."""

    def install(handler):
        real_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(financial_collector.httpx, "AsyncClient", factory)

    return install


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    """with_retry 백오프 대기를 제거해 재시도 테스트를 즉시 끝낸다."""

    async def _instant(_seconds):
        return None

    monkeypatch.setattr("services.collector.tools.with_retry.asyncio.sleep", _instant)


async def test_cfs_hit_records_cfs(install_transport):
    """연결재무제표(CFS)에서 수치를 집으면 fs_div='CFS'로 보존한다."""
    install_transport(lambda request: httpx.Response(200, json=_FS_OK))

    statements = await FinancialCollector(companies=[COMPANY]).collect(2025)

    assert len(statements) == 1
    assert statements[0].fs_div == "CFS"
    assert statements[0].revenue == 1000
    assert statements[0].to_record()["fs_div"] == "CFS"


async def test_ofs_fallback_records_ofs(install_transport):
    """CFS가 013(데이터 없음)이면 개별(OFS)로 폴백하고 fs_div='OFS'를 보존한다."""

    def handler(request):
        fs_div = request.url.params.get("fs_div")
        return httpx.Response(200, json=_FS_EMPTY if fs_div == "CFS" else _FS_OK)

    install_transport(handler)

    statements = await FinancialCollector(companies=[COMPANY]).collect(2025)

    assert len(statements) == 1
    assert statements[0].fs_div == "OFS"
    assert statements[0].total_assets == 5000


async def test_transient_error_is_retried(install_transport):
    """첫 요청이 일시 네트워크 오류(TransportError)면 재시도해 수집을 회복한다."""
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("일시 연결 실패")
        return httpx.Response(200, json=_FS_OK)

    install_transport(handler)

    statements = await FinancialCollector(companies=[COMPANY]).collect(2025)

    assert calls["n"] == 2  # 1차 실패 → 2차 성공
    assert len(statements) == 1
    assert statements[0].fs_div == "CFS"
