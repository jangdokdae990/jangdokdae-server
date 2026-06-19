"""DART 공시 수집기 — OpenDART REST API(list.json) 기반 공시 목록 수집.

역할:
    추적 기업의 정기보고서(A)·주요사항보고서(B) 공시 메타데이터(접수번호·제목·
    공시일 등)를 기간 단위로 수집한다. 공시 본문(content)은 여기서 받지 않고
    분석 단계에서 별도 fetch한다 — 현재 content는 NULL로 저장된다.

핵심 동작:
    - collect(): (기업 × 공시유형) 조합을 작업 단위로 만들어 병렬 수집하고,
      각 조합 단위로 에러를 격리한다. total_page 기준으로 페이지네이션한다.
    - status="013"(데이터 없음)은 정상으로 간주해 조용히 종료한다.
    - 예외 로깅은 redact_secrets로 감싸 crtfc_key 유출을 막는다.

경계:
    입력 = company_loader의 list[StockSymbol](corp_code 있는 기업만 대상)
    / 출력 = CollectedDisclosure.to_record() → save_tool.upsert_disclosures (rcept_no UPSERT).
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.config import settings
from services.collector.stock_symbols import ALL_STOCKS, StockSymbol
from services.collector.tools.redact import redact_secrets
from services.collector.tools.with_retry import with_retry

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
                    "공시 수집 실패 corp_code=%s type=%s err=%s",
                    company.corp_code,
                    dtype,
                    redact_secrets(batch),
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
            data = await self._get_page(client, params)
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
                d
                for item in data.get("list", [])
                if (d := self._to_disclosure(item, company, dtype)) is not None
            )
            if page >= int(data.get("total_page", 1)):
                break
            page += 1
        return results

    @with_retry(max_attempts=2, retry_on=httpx.TransportError)
    async def _get_page(
        self, client: httpx.AsyncClient, params: dict[str, str | int]
    ) -> dict:
        """list.json 한 페이지를 조회. 일시 네트워크 오류만 1회 더 시도해 흡수한다 —
        4xx/5xx·status 비정상은 전파하여 Airflow Task 재시도/격리에 맡긴다."""
        response = await client.get(DART_LIST_URL, params=params)
        response.raise_for_status()
        data: dict = response.json()
        return data

    @staticmethod
    def _to_disclosure(
        item: dict, company: StockSymbol, dtype: str
    ) -> CollectedDisclosure | None:
        # rcept_no·rcept_dt가 없거나 형식이 깨진 항목은 그 항목만 건너뛴다.
        # (직접 접근 시 KeyError/ValueError가 같은 페이지의 정상 공시까지 통째로 유실시킴)
        rcept_no = (item.get("rcept_no") or "").strip()
        rcept_dt = (item.get("rcept_dt") or "").strip()
        if not rcept_no or not rcept_dt:
            logger.warning("공시 항목 누락 corp_code=%s rcept_no=%r", company.corp_code, rcept_no)
            return None
        try:
            disclosed_at = datetime.strptime(rcept_dt, "%Y%m%d")
        except ValueError:
            logger.warning("공시일 형식 오류 rcept_no=%s rcept_dt=%r", rcept_no, rcept_dt)
            return None
        stock_code = (item.get("stock_code") or "").strip() or None
        return CollectedDisclosure(
            rcept_no=rcept_no,
            title=(item.get("report_nm") or "").strip(),
            corp_name=(item.get("corp_name") or "").strip(),
            corp_code=item.get("corp_code") or company.corp_code,
            stock_code=stock_code,
            disclosure_type=dtype,
            disclosed_at=disclosed_at,
        )
