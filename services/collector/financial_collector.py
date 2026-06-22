"""재무제표 수집기 — DART fnlttSinglAcntAll.json(구조화 재무 API) 기반.

DART 구조화 JSON API 사용 (HTML 파싱 불필요, 비동기, 경량).
매출액·영업이익·당기순이익·자산총계 4개 핵심 수치를 수집한다.
"""

import asyncio
import logging
from dataclasses import dataclass

import httpx

from app.config import settings
from services.collector.stock_symbols import ALL_STOCKS, StockSymbol
from services.collector.tools.redact import redact_secrets
from services.collector.tools.with_retry import with_retry

logger = logging.getLogger(__name__)

DART_FS_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
DEFAULT_TIMEOUT = 15.0

# reprt_code → 분기 (사업보고서=4)
REPORT_QUARTER: dict[str, int] = {"11013": 1, "11012": 2, "11014": 3, "11011": 4}

# 지표 → (account_nm 후보, 허용 재무제표 구분 sj_div)
# 손익 항목은 회사에 따라 IS(손익) 또는 CIS(포괄손익)에 보고됨 → 둘 다 허용
_INCOME = frozenset({"IS", "CIS"})
_METRICS: dict[str, tuple[tuple[str, ...], frozenset[str]]] = {
    "revenue": (("매출액", "수익(매출액)", "영업수익"), _INCOME),
    "operating_income": (("영업이익", "영업이익(손실)"), _INCOME),
    "net_income": (("당기순이익", "당기순이익(손실)"), _INCOME),
    "total_assets": (("자산총계",), frozenset({"BS"})),
}


@dataclass(frozen=True)
class CollectedFinancial:
    corp_code: str
    corp_name: str
    year: int
    quarter: int
    revenue: int | None
    operating_income: int | None
    net_income: int | None
    total_assets: int | None
    rcept_no: str | None = None  # 원천 사업보고서 접수번호 (추적 키)
    fs_div: str | None = None  # 수치 출처 재무제표 구분 (CFS=연결 / OFS=개별)

    def to_record(self) -> dict[str, object]:
        # save_tool.upsert_financial_statements / FinancialStatement 컬럼 입력 형식
        return {
            "corp_code": self.corp_code,
            "corp_name": self.corp_name,
            "rcept_no": self.rcept_no,
            "year": self.year,
            "quarter": self.quarter,
            "revenue": self.revenue,
            "operating_income": self.operating_income,
            "net_income": self.net_income,
            "total_assets": self.total_assets,
            "fs_div": self.fs_div,
        }


class FinancialCollector:
    def __init__(
        self, companies: list[StockSymbol] | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        base = companies if companies is not None else ALL_STOCKS
        self.companies = [c for c in base if c.corp_code]  # corp_code 있는 기업만
        self.timeout = timeout

    async def collect(
        self, bsns_year: int, reprt_code: str = "11011"
    ) -> list[CollectedFinancial]:
        """기업별 재무제표를 수집(reprt_code 기본=사업보고서). 기업 단위 에러 격리."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            results = await asyncio.gather(
                *[self._fetch(client, c, bsns_year, reprt_code) for c in self.companies],
                return_exceptions=True,
            )
        statements: list[CollectedFinancial] = []
        for company, result in zip(self.companies, results):
            if isinstance(result, BaseException):
                logger.error(
                    "재무제표 수집 실패 corp_code=%s err=%s",
                    company.corp_code,
                    redact_secrets(result),
                )
                continue
            if result is not None:
                statements.append(result)
        return statements

    async def _fetch(
        self, client: httpx.AsyncClient, company: StockSymbol, bsns_year: int, reprt_code: str
    ) -> CollectedFinancial | None:
        # 연결재무제표(CFS) 우선, 없으면 개별재무제표(OFS) 폴백.
        # 종속회사가 없어 연결을 작성하지 않는 기업은 CFS가 013(데이터 없음)이라
        # CFS만 조회하면 재무 수치가 통째로 누락된다.
        fs_div = "CFS"
        accounts = await self._fetch_accounts(client, company, bsns_year, reprt_code, fs_div)
        if accounts is None:
            fs_div = "OFS"
            accounts = await self._fetch_accounts(client, company, bsns_year, reprt_code, fs_div)
        if accounts is None:
            logger.warning(
                "재무제표 없음 corp_code=%s year=%s (CFS·OFS 모두 데이터 없음)",
                company.corp_code,
                bsns_year,
            )
            return None
        return CollectedFinancial(
            corp_code=company.corp_code,
            corp_name=company.name,
            year=bsns_year,
            quarter=REPORT_QUARTER[reprt_code],
            revenue=self._extract(accounts, *_METRICS["revenue"]),
            operating_income=self._extract(accounts, *_METRICS["operating_income"]),
            net_income=self._extract(accounts, *_METRICS["net_income"]),
            total_assets=self._extract(accounts, *_METRICS["total_assets"]),
            rcept_no=self._extract_rcept_no(accounts),
            fs_div=fs_div,  # 수치를 실제로 취한 재무제표 구분 보존
        )

    @with_retry(max_attempts=2, retry_on=httpx.TransportError)
    async def _fetch_accounts(
        self,
        client: httpx.AsyncClient,
        company: StockSymbol,
        bsns_year: int,
        reprt_code: str,
        fs_div: str,
    ) -> list[dict] | None:
        """단일 fs_div(CFS/OFS) 재무 계정 목록을 조회. 데이터 없으면 None.

        일시 네트워크 오류(TransportError)만 1회 더 시도해 흡수한다 — 4xx/5xx·
        status=013(데이터 없음)은 전파하여 Airflow Task 재시도/폴백에 맡긴다.
        """
        params = {
            "crtfc_key": settings.opendart_api_key,
            "corp_code": company.corp_code,
            "bsns_year": str(bsns_year),
            "reprt_code": reprt_code,
            "fs_div": fs_div,
        }
        response = await client.get(DART_FS_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "000":  # 013=데이터 없음 포함
            return None
        accounts: list[dict] = data.get("list", [])
        return accounts or None

    @staticmethod
    def _extract_rcept_no(accounts: list[dict]) -> str | None:
        # fnlttSinglAcntAll 응답의 각 계정 행에 동일 rcept_no가 실린다 — 첫 행에서 취함
        for acc in accounts:
            rcept_no = (acc.get("rcept_no") or "").strip()
            if rcept_no:
                return rcept_no
        return None

    @staticmethod
    def _extract(
        accounts: list[dict], names: tuple[str, ...], sj_divs: frozenset[str]
    ) -> int | None:
        for acc in accounts:
            if acc.get("sj_div") in sj_divs and acc.get("account_nm") in names:
                raw = (acc.get("thstrm_amount") or "").replace(",", "").strip()
                if raw and raw != "-":
                    try:
                        return int(raw)
                    except ValueError:
                        return None
        return None
