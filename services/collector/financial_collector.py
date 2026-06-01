"""재무제표 수집기 — DART fnlttSinglAcntAll.json(구조화 재무 API) 기반.

설계의 dart-fss 대신 DART 구조화 JSON API 사용 (HTML 파싱 불필요, 비동기, 경량).
매출액·영업이익·당기순이익·자산총계 4개 핵심 수치를 수집한다.
"""

import asyncio
import logging
from dataclasses import dataclass

import httpx

from app.config import settings
from services.collector.stock_symbols import ALL_STOCKS, StockSymbol

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

    def to_record(self) -> dict[str, object]:
        # save_tool.upsert_financial_statements / FinancialStatement 컬럼 입력 형식
        return {
            "corp_code": self.corp_code,
            "corp_name": self.corp_name,
            "year": self.year,
            "quarter": self.quarter,
            "revenue": self.revenue,
            "operating_income": self.operating_income,
            "net_income": self.net_income,
            "total_assets": self.total_assets,
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
                logger.error("재무제표 수집 실패 corp_code=%s err=%s", company.corp_code, result)
                continue
            if result is not None:
                statements.append(result)
        return statements

    async def _fetch(
        self, client: httpx.AsyncClient, company: StockSymbol, bsns_year: int, reprt_code: str
    ) -> CollectedFinancial | None:
        params = {
            "crtfc_key": settings.opendart_api_key,
            "corp_code": company.corp_code,
            "bsns_year": str(bsns_year),
            "reprt_code": reprt_code,
            "fs_div": "CFS",  # 연결재무제표
        }
        response = await client.get(DART_FS_URL, params=params)
        response.raise_for_status()
        data = response.json()
        status = data.get("status")
        if status != "000":  # 013=데이터 없음 포함
            logger.warning(
                "재무제표 응답 없음/비정상 corp_code=%s year=%s status=%s",
                company.corp_code,
                bsns_year,
                status,
            )
            return None
        accounts = data.get("list", [])
        return CollectedFinancial(
            corp_code=company.corp_code,
            corp_name=company.name,
            year=bsns_year,
            quarter=REPORT_QUARTER[reprt_code],
            revenue=self._extract(accounts, *_METRICS["revenue"]),
            operating_income=self._extract(accounts, *_METRICS["operating_income"]),
            net_income=self._extract(accounts, *_METRICS["net_income"]),
            total_assets=self._extract(accounts, *_METRICS["total_assets"]),
        )

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
