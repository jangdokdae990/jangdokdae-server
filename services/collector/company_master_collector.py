"""기업 마스터 동기화 — DART 전체 corp_code + PyKRX 섹터/마켓 정보.

DART corpCode.xml(ZIP)에서 KRX 종목코드 있는 상장사만 추출하고,
PyKRX로 sector·market 정보를 병합해 company_entities 테이블을 업데이트한다.

- 기존 레코드: sector_id 업데이트
- 신규 레코드: is_active=False로 삽입 (기존 추적 종목 영향 없음)
"""

import asyncio
import io
import logging
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.orm_models.company_entity import CompanyEntity
from utils.dates import now_kst

logger = logging.getLogger(__name__)

DART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class CorpInfo:
    dart_code: str   # 8자리 DART 기업코드
    name: str        # DART 기업명
    krx_code: str    # 6자리 KRX 종목코드


async def fetch_dart_corp_codes(timeout: float = DEFAULT_TIMEOUT) -> list[CorpInfo]:
    """DART corpCode.xml ZIP에서 KRX 상장사 목록을 반환."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        params = {"crtfc_key": settings.opendart_api_key}
        response = await client.get(DART_CORP_CODE_URL, params=params)
        response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        xml_text = z.read("CORPCODE.xml").decode("utf-8", errors="replace")

    root = ET.fromstring(xml_text)
    corps: list[CorpInfo] = []
    for item in root.findall(".//list"):
        krx_code = (item.findtext("stock_code") or "").strip()
        if not krx_code:  # 비상장사 제외
            continue
        dart_code = (item.findtext("corp_code") or "").strip()
        name = (item.findtext("corp_name") or "").strip()
        if dart_code and name:
            corps.append(CorpInfo(dart_code=dart_code, name=name, krx_code=krx_code))
    return corps


def fetch_krx_sector_market(date_str: str) -> dict[str, tuple[str, str]]:
    """PyKRX로 KOSPI·KOSDAQ 전종목 (market, sector) 반환.
    반환: {krx_code: (market, sector_name)}
    """
    from pykrx import stock  # 동기 라이브러리

    result: dict[str, tuple[str, str]] = {}
    for market in ("KOSPI", "KOSDAQ"):
        try:
            df = stock.get_market_sector_classifications(date_str, market)
            for krx_code, row in df.iterrows():
                result[str(krx_code)] = (market, row["업종명"])
        except Exception as exc:
            logger.warning("PyKRX 섹터 조회 실패 market=%s err=%s", market, exc)
    return result


async def sync_company_master(db: AsyncSession) -> dict[str, int]:
    """DART + PyKRX 데이터로 company_entities 테이블을 동기화.

    기존 레코드는 market·corp_code만 갱신하고 is_active·sector_id·name_ko는 보존한다.
    신규 레코드는 is_active=False로 삽입돼 기존 추적 종목에 영향을 주지 않는다.

    Returns:
        {"total": 동기화한 전체 상장사 수, "existing": 동기화 전 기존 레코드 수}
        — ON CONFLICT DO UPDATE는 insert/update를 구분하지 못하므로(둘 다 영향 행으로
        집계됨), 정확한 신규/갱신 건수 대신 동기화 전 기준 수치를 함께 반환한다.
    """
    today = now_kst().strftime("%Y%m%d")

    logger.info("DART corp_code 전체 다운로드 중...")
    corps = await fetch_dart_corp_codes()
    logger.info("DART 상장사: %d개", len(corps))

    logger.info("PyKRX 섹터/마켓 조회 중...")
    sector_market = await asyncio.to_thread(fetch_krx_sector_market, today)
    logger.info("PyKRX 종목: %d개", len(sector_market))

    # 동기화 전 기존 레코드 수 (신규 유입 규모 가늠용)
    existing = await db.scalar(select(func.count()).select_from(CompanyEntity)) or 0

    # 신규 레코드 upsert (기존은 market·corp_code만 갱신, 그 외 컬럼은 보존)
    # NOTE: PyKRX 업종명 → sectors.sector_id 매핑은 미구현. 현재 sector_id는
    #       seed/수동 관리에 의존하며, 신규 종목은 sector 미분류 상태로 적재된다.
    records = []
    for corp in corps:
        market, _ = sector_market.get(corp.krx_code, (None, None))
        records.append({
            "stock_code": corp.krx_code,
            "name_ko": corp.name,
            "corp_code": corp.dart_code,
            "market": market or "UNKNOWN",
            "aliases": [],
            "is_active": False,  # 신규 종목은 기본 비활성화
        })

    if not records:
        return {"total": 0, "existing": existing}

    # 배치 처리 (PostgreSQL 바인드 파라미터 한계 회피 + DB 부하 완화)
    BATCH = 500
    for i in range(0, len(records), BATCH):
        batch = records[i: i + BATCH]
        stmt = pg_insert(CompanyEntity).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_code"],
            set_={
                # PyKRX 조회 실패 등으로 market이 "UNKNOWN"이면 기존 정상값을 보존
                # (이미 KOSPI/KOSDAQ로 분류된 추적 종목을 UNKNOWN으로 퇴행시키지 않음)
                "market": func.coalesce(
                    func.nullif(stmt.excluded.market, "UNKNOWN"), CompanyEntity.market
                ),
                "corp_code": stmt.excluded.corp_code,
            },
        )
        await db.execute(stmt)
        await db.commit()

    return {"total": len(records), "existing": existing}
