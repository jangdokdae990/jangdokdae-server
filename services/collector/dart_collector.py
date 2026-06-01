"""DART 공시 수집기 — opendart REST API(list.json) 기반."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.config import settings
from services.collector.stock_symbols import ALL_STOCKS, StockSymbol

logger = logging.getLogger(__name__)

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DEFAULT_DISCLOSURE_TYPES = ("A", "B")  # A=정기보고서(사업·분기·반기), B=주요사항보고서
DEFAULT_TIMEOUT = 10.0
PAGE_COUNT = 100


@dataclass(frozen=True)
class CollectedDisclosure:
    rcept_no: str
    title: str
    corp_name: str
    corp_code: str
    stock_code: str | None
    disclosure_type: str
    disclosed_at: datetime  # KST naive (rcept_dt 기준 자정)

    def to_record(self) -> dict[str, object]:
        # save_tool.upsert_disclosures / Disclosure 컬럼 입력 형식 (content는 후속 fetch)
        return {
            "rcept_no": self.rcept_no,
            "title": self.title,
            "corp_name": self.corp_name,
            "corp_code": self.corp_code,
            "stock_code": self.stock_code,
            "disclosure_type": self.disclosure_type,
            "disclosed_at": self.disclosed_at,
        }


class DARTCollector:
    def __init__(
        self, companies: list[StockSymbol] | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> None:
        base = companies if companies is not None else ALL_STOCKS
        self.companies = [c for c in base if c.corp_code]  # corp_code 있는 기업만 DART 대상
        self.timeout = timeout

    async def collect(self, bgn_de: str, end_de: str) -> list[CollectedDisclosure]:
        """기간(YYYYMMDD) 동안 추적 기업의 공시를 수집. (기업×유형) 단위 에러 격리."""
        jobs = [
            (company, dtype)
            for company in self.companies
            for dtype in DEFAULT_DISCLOSURE_TYPES
        ]
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            batches = await asyncio.gather(
                *[self._fetch(client, company, dtype, bgn_de, end_de) for company, dtype in jobs],
                return_exceptions=True,
            )
        disclosures: list[CollectedDisclosure] = []
        for (company, dtype), batch in zip(jobs, batches):
            if isinstance(batch, BaseException):
                logger.error(
                    "공시 수집 실패 corp_code=%s type=%s err=%s", company.corp_code, dtype, batch
                )
                continue
            disclosures.extend(batch)
        return disclosures

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        company: StockSymbol,
        dtype: str,
        bgn_de: str,
        end_de: str,
    ) -> list[CollectedDisclosure]:
        results: list[CollectedDisclosure] = []
        page = 1
        while True:
            params: dict[str, str | int] = {
                "crtfc_key": settings.opendart_api_key,
                "corp_code": company.corp_code,
                "pblntf_ty": dtype,
                "bgn_de": bgn_de,
                "end_de": end_de,
                "page_no": page,
                "page_count": PAGE_COUNT,
            }
            response = await client.get(DART_LIST_URL, params=params)
            response.raise_for_status()
            data = response.json()
            status = data.get("status")
            if status == "013":  # 조회된 데이터 없음 (정상)
                break
            if status != "000":
                logger.warning(
                    "DART 응답 비정상 corp_code=%s type=%s status=%s msg=%s",
                    company.corp_code,
                    dtype,
                    status,
                    data.get("message"),
                )
                break
            results.extend(
                self._to_disclosure(item, company, dtype) for item in data.get("list", [])
            )
            if page >= int(data.get("total_page", 1)):
                break
            page += 1
        return results

    @staticmethod
    def _to_disclosure(item: dict, company: StockSymbol, dtype: str) -> CollectedDisclosure:
        stock_code = (item.get("stock_code") or "").strip() or None
        return CollectedDisclosure(
            rcept_no=item["rcept_no"],
            title=(item.get("report_nm") or "").strip(),
            corp_name=(item.get("corp_name") or "").strip(),
            corp_code=item.get("corp_code") or company.corp_code,
            stock_code=stock_code,
            disclosure_type=dtype,
            disclosed_at=datetime.strptime(item["rcept_dt"], "%Y%m%d"),
        )
