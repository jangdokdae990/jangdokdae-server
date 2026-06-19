"""사업보고서 수집기 — DART document.xml(ZIP) 기반 섹션 청킹.

1. DART list.json으로 기업별 최신 사업보고서 rcept_no 조회
2. document.xml API로 ZIP 다운로드 → XML 텍스트 추출
3. dart_preprocessor로 3개 섹션 파싱 → ReportChunk 레코드 생성
"""

import asyncio
import io
import logging
import zipfile
from dataclasses import dataclass

import httpx

from app.config import settings
from services.collector.stock_symbols import StockSymbol
from services.collector.tools.redact import redact_secrets
from services.collector.tools.with_retry import with_retry
from services.preprocessor.company_preprocessor import parse_report_sections

logger = logging.getLogger(__name__)

DART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
DART_DOC_URL = "https://opendart.fss.or.kr/api/document.xml"
DEFAULT_TIMEOUT = 20.0


@dataclass(frozen=True)
class CollectedReportChunk:
    corp_code: str
    corp_name: str
    report_year: int
    rcept_no: str
    chunk_type: str    # "business_summary" | "director_analysis" | "audit_opinion"
    subsection: str    # 소제목 (없으면 "")
    content: str

    def to_record(self) -> dict[str, object]:
        return {
            "corp_code": self.corp_code,
            "corp_name": self.corp_name,
            "report_year": self.report_year,
            "rcept_no": self.rcept_no,
            "chunk_type": self.chunk_type,
            "subsection": self.subsection,
            "content": self.content,
        }


class ReportCollector:
    def __init__(
        self,
        companies: list[StockSymbol] | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.companies = [c for c in (companies or []) if c.corp_code]
        self.timeout = timeout

    async def collect(self, bsns_year: int) -> list[CollectedReportChunk]:
        """기업별 사업보고서를 수집해 청크 목록을 반환. 기업 단위 에러 격리."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            results = await asyncio.gather(
                *[self._collect_one(client, company, bsns_year) for company in self.companies],
                return_exceptions=True,
            )
        chunks: list[CollectedReportChunk] = []
        for company, result in zip(self.companies, results):
            if isinstance(result, BaseException):
                logger.error(
                    "사업보고서 수집 실패 corp_code=%s err=%s",
                    company.corp_code,
                    redact_secrets(result),
                )
                continue
            chunks.extend(result)
        return chunks

    async def _collect_one(
        self, client: httpx.AsyncClient, company: StockSymbol, bsns_year: int
    ) -> list[CollectedReportChunk]:
        rcept_no = await self._find_annual_report(client, company.corp_code, bsns_year)
        if not rcept_no:
            logger.warning("사업보고서 없음 corp_code=%s year=%s", company.corp_code, bsns_year)
            return []

        xml_text = await self._fetch_document_xml(client, rcept_no)
        if not xml_text:
            return []

        sections = parse_report_sections(xml_text)
        chunks: list[CollectedReportChunk] = []
        for chunk_type, items in sections.items():
            for item in items:
                if not item["content"].strip():
                    continue
                chunks.append(
                    CollectedReportChunk(
                        corp_code=company.corp_code,
                        corp_name=company.name,
                        report_year=bsns_year,
                        rcept_no=rcept_no,
                        chunk_type=chunk_type,
                        subsection=item.get("subsection", ""),
                        content=item["content"],
                    )
                )
        return chunks

    @with_retry(max_attempts=2, retry_on=httpx.TransportError)
    async def _find_annual_report(
        self, client: httpx.AsyncClient, corp_code: str, bsns_year: int
    ) -> str | None:
        """해당 기업·연도의 사업보고서(11011) rcept_no를 반환. 없으면 None.

        일시 네트워크 오류(TransportError)만 1회 더 시도해 흡수한다."""
        bgn_de = f"{bsns_year}0101"
        end_de = f"{bsns_year + 1}0630"  # 사업보고서는 다음 해 3월까지 제출
        params: dict[str, str | int] = {
            "crtfc_key": settings.opendart_api_key,
            "corp_code": corp_code,
            "pblntf_ty": "A",
            "bgn_de": bgn_de,
            "end_de": end_de,
            "page_no": 1,
            "page_count": 10,
        }
        response = await client.get(DART_LIST_URL, params=params)
        response.raise_for_status()
        data = response.json()
        if data.get("status") != "000":
            return None
        # 정정 공시가 여러 건일 수 있고 list.json 정렬이 보장되지 않으므로,
        # 접수일(rcept_dt) 최신 사업보고서를 선택해 정정 전 원본을 집는 것을 방지
        candidates = [
            item
            for item in data.get("list", [])
            if "사업보고서" in (item.get("report_nm") or "") and item.get("rcept_no")
        ]
        if not candidates:
            return None
        latest = max(candidates, key=lambda it: it.get("rcept_dt") or "")
        return str(latest["rcept_no"])

    @with_retry(max_attempts=2, retry_on=httpx.TransportError)
    async def _fetch_document_xml(
        self, client: httpx.AsyncClient, rcept_no: str
    ) -> str | None:
        """DART document.xml API로 ZIP을 다운로드해 XML 텍스트를 반환.

        일시 네트워크 오류(TransportError)만 1회 더 시도해 흡수한다."""
        params = {"crtfc_key": settings.opendart_api_key, "rcept_no": rcept_no}
        response = await client.get(DART_DOC_URL, params=params)
        response.raise_for_status()
        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as z:
                xml_name = next(
                    (n for n in z.namelist() if n.lower().endswith(".xml")), None
                )
                if not xml_name:
                    logger.warning("ZIP에 XML 없음 rcept_no=%s", rcept_no)
                    return None
                return z.read(xml_name).decode("utf-8", errors="replace")
        except zipfile.BadZipFile:
            logger.warning("ZIP 파싱 실패 rcept_no=%s", rcept_no)
            return None
