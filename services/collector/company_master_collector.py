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
from app.db.orm_models.sector import Sector
from utils.dates import now_kst

logger = logging.getLogger(__name__)

DART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
DEFAULT_TIMEOUT = 30.0

# KRX 업종명(PyKRX get_market_sector_classifications) → GICS 섹터 코드(sectors.gics_code).
# KRX 업종은 GICS 섹터와 입도가 달라 일부(일반서비스·유통·운송장비·기타제조·농림어업)는
# 대표 업종 기준 근사 매핑이다. KRX엔 별도 '에너지' 업종이 없어 GICS 에너지(10)는 비는 게 정상.
# 미매핑 업종은 sector_id를 NULL로 남긴다(기존 값은 보존).
KRX_SECTOR_TO_GICS: dict[str, str] = {
    "전기·전자": "45",          # IT
    "IT 서비스": "45",          # IT
    "화학": "15",               # 소재
    "기계·장비": "20",          # 산업재
    "제약": "35",               # 헬스케어
    "일반서비스": "25",         # 경기소비재(근사 — 서비스 다수)
    "유통": "25",               # 경기소비재(근사 — 도소매)
    "운송장비·부품": "25",      # 경기소비재(근사 — 자동차 다수, 조선·방산 일부 산업재)
    "금속": "15",               # 소재
    "금융": "40",               # 금융
    "의료·정밀기기": "35",      # 헬스케어
    "기타금융": "40",           # 금융
    "음식료·담배": "30",        # 필수소비재
    "오락·문화": "50",          # 커뮤니케이션서비스
    "건설": "20",               # 산업재
    "섬유·의류": "25",          # 경기소비재
    "비금속": "15",             # 소재
    "운송·창고": "20",          # 산업재
    "증권": "40",               # 금융
    "종이·목재": "15",          # 소재
    "부동산": "60",             # 부동산
    "기타제조": "20",           # 산업재(근사)
    "보험": "40",               # 금융
    "통신": "50",               # 커뮤니케이션서비스
    "전기·가스": "55",          # 유틸리티
    "은행": "40",               # 금융
    "농업 임업 및 어업": "30",  # 필수소비재(근사)
    "전기·가스·수도": "55",     # 유틸리티
    "출판·매체복제": "50",      # 커뮤니케이션서비스
}


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

    # GICS 섹터 코드 → sector_id (KRX 업종명 매핑 결과를 FK로 변환)
    sector_rows = (await db.execute(select(Sector.id, Sector.gics_code))).all()
    gics_to_sector_id = {gics: sid for sid, gics in sector_rows}
    if not gics_to_sector_id:
        # sectors 미시드 → 아래 매핑이 전부 NULL이 된다. fail-fast 대신 경보로 끌어올린다.
        logger.warning(
            "sectors 테이블이 비어 있음 — 섹터 시드 누락 의심, 모든 종목이 sector_id=NULL로 적재됨"
        )

    # 신규 레코드 upsert (기존은 market·corp_code·sector_id 갱신, name_ko·is_active는 보존)
    # PyKRX 업종명 → GICS 섹터(KRX_SECTOR_TO_GICS) → sector_id. 미매핑/조회실패는 NULL.
    records: list[dict[str, object]] = []
    mapped = 0
    for corp in corps:
        market, krx_sector = sector_market.get(corp.krx_code, (None, None))
        gics = KRX_SECTOR_TO_GICS.get(krx_sector or "")
        sector_id = gics_to_sector_id.get(gics) if gics else None
        if sector_id is not None:
            mapped += 1
        records.append({
            "stock_code": corp.krx_code,
            "name_ko": corp.name,
            "corp_code": corp.dart_code,
            "market": market or "UNKNOWN",
            "sector_id": sector_id,
            "aliases": [],
            "is_active": False,  # 신규 종목은 기본 비활성화
        })
    if records and mapped == 0:
        # 종목은 있는데 매핑이 0건 — 시드 누락·KRX 업종명 변경 등 데이터 불일치 신호.
        logger.warning(
            "섹터 매핑 0건 — 시드 누락 또는 KRX 업종명↔GICS 불일치 의심 (records=%d)", len(records)
        )
    else:
        logger.info("섹터 매핑: %d/%d (KRX 업종명 → GICS sector_id)", mapped, len(records))

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
                # 미매핑(NULL)이면 기존 sector_id를 보존, 매핑됐으면 갱신
                "sector_id": func.coalesce(
                    stmt.excluded.sector_id, CompanyEntity.sector_id
                ),
            },
        )
        await db.execute(stmt)
        await db.commit()

    return {"total": len(records), "existing": existing}


# --- UNKNOWN 시장 재분류 ---

# FDR KRX 리스팅이 주는 국내 거래소 값.
DOMESTIC_KRX_MARKETS = frozenset({"KOSPI", "KOSDAQ", "KONEX"})


def plan_reclassification(
    unknown_codes: list[str], krx_market_map: dict[str, str]
) -> tuple[dict[str, str], list[str]]:
    """UNKNOWN 종목코드를 KRX 시장맵으로 (재분류 {code: market}, 비활성 [code])로 가른다."""
    reclassify: dict[str, str] = {}
    deactivate: list[str] = []
    for code in unknown_codes:
        market = krx_market_map.get(code)
        if market in DOMESTIC_KRX_MARKETS:
            reclassify[code] = market
        else:
            deactivate.append(code)
    return reclassify, deactivate


def _fetch_krx_market_map() -> dict[str, str]:
    """FDR KRX 전체 리스팅 → {6자리 종목코드: 시장(KOSPI/KOSDAQ/KONEX)}. 동기 — to_thread로 호출."""
    import FinanceDataReader as fdr

    df = fdr.StockListing("KRX")
    market_map: dict[str, str] = {}
    for record in df.to_dict("records"):
        code = str(record.get("Code") or record.get("Symbol") or "").strip().zfill(6)
        market = str(record.get("Market") or "").strip().upper()
        if code and market:
            market_map[code] = market
    return market_map


async def reclassify_unknown_markets(db: AsyncSession) -> dict[str, int]:
    """market='UNKNOWN' 국내 종목을 KRX 실거래소로 재분류, 미해결은 is_active=False.

    UNKNOWN은 PyKRX KOSPI/KOSDAQ 분류에서 못 찾은 종목(KONEX·신규/상장폐지 등)이다. FDR KRX
    리스팅의 Market으로 재매칭하고, 끝까지 안 잡히면(상장폐지 등) 온보딩 비노출로 정리한다.
    """
    rows = (
        await db.execute(select(CompanyEntity).where(CompanyEntity.market == "UNKNOWN"))
    ).scalars().all()
    if not rows:
        return {"unknown": 0, "reclassified": 0, "deactivated": 0}

    krx_market_map = await asyncio.to_thread(_fetch_krx_market_map)
    reclassify, _deactivate = plan_reclassification(
        [r.stock_code for r in rows], krx_market_map
    )

    reclassified = 0
    deactivated = 0
    for entity in rows:
        new_market = reclassify.get(entity.stock_code)
        if new_market:
            entity.market = new_market
            reclassified += 1
        else:
            entity.is_active = False
            deactivated += 1
    await db.commit()

    result = {"unknown": len(rows), "reclassified": reclassified, "deactivated": deactivated}
    logger.info("UNKNOWN 재분류: %s", result)
    return result
