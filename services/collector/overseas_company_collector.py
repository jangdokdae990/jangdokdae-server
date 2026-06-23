"""해외 종목 유니버스 동기화 — FinanceDataReader로 미국 주요 지수/ETF 적재.

S&P500(FDR StockListing) + NASDAQ-100(큐레이션 티커) + 미국 대표 ETF(큐레이션)를
``company_entities``에 ``is_active=True``로 적재한다. 온보딩 "관심 설정 → 종목"에 해외가
보이게 하는 게 목적이며, 분석 데이터(재무·공시·RAG)는 범위 밖이다(설계 docs/design/13).

- **시장 버킷**: ``CompanyEntity.market``이 단일 값이라 서로소로 배정. 우선순위는
  ``OVERSEAS_BUCKET_PRIORITY``(ETF > NASDAQ > SP500) — 상장 거래소 기준 우선이라 유명
  기술주(AAPL·NVDA)는 ``NASDAQ``, NYSE 대형주(JPM·XOM)는 ``SP500``으로 들어간다.
- **격리**: 해외는 ``corp_code=NULL``이라 DART 수집기(dart/financial/report)가 자동 제외한다
  (각 수집기가 ``corp_code`` 보유분만 처리).
- **멱등**: ``ON CONFLICT(stock_code) DO UPDATE`` — 재실행 안전. 영문 티커라 국내 6자리 코드와
  키 충돌 없음.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.orm_models.company_entity import CompanyEntity
from app.db.orm_models.sector import Sector

logger = logging.getLogger(__name__)

# 버킷 우선순위(서로소 배정). 뒤집고 싶으면 이 한 줄만 바꾼다.
OVERSEAS_BUCKET_PRIORITY = ("US_ETF", "NASDAQ", "SP500")

# FDR S&P500 리스팅의 GICS 영문 섹터명 → sectors.gics_code(섹터 레벨 2자리).
# Sector.name_en이 동일 GICS 영문명이지만, 표기 흔들림(Health Care 등)에 안전하도록 명시 매핑한다.
US_GICS_SECTOR_TO_CODE: dict[str, str] = {
    "Energy": "10",
    "Materials": "15",
    "Industrials": "20",
    "Consumer Discretionary": "25",
    "Consumer Staples": "30",
    "Health Care": "35",
    "Financials": "40",
    "Information Technology": "45",
    "Communication Services": "50",
    "Utilities": "55",
    "Real Estate": "60",
}

# NASDAQ-100 구성종목 티커(2026-06 기준 큐레이션). 지수 편출입이 잦아 주기적 갱신 대상.
# 대부분 S&P500과 겹치며, 우선순위상 이 집합이 NASDAQ 버킷을 차지한다.
NASDAQ_100_TICKERS: frozenset[str] = frozenset({
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "AVGO", "GOOGL", "GOOG", "TSLA", "COST",
    "NFLX", "AMD", "PEP", "ADBE", "LIN", "CSCO", "TMUS", "INTU", "QCOM", "TXN",
    "AMGN", "ISRG", "AMAT", "BKNG", "HON", "CMCSA", "VRTX", "ADP", "PANW", "MU",
    "ADI", "GILD", "MELI", "LRCX", "SBUX", "INTC", "REGN", "KLAC", "MDLZ", "PYPL",
    "SNPS", "CDNS", "MAR", "CRWD", "ASML", "CSX", "ABNB", "ORLY", "FTNT", "PDD",
    "MRVL", "DASH", "ADSK", "WDAY", "NXPI", "ROP", "TTD", "CHTR", "MNST", "PCAR",
    "AEP", "PAYX", "KDP", "ODP", "FAST", "CPRT", "ROST", "BKR", "KHC", "EA",
    "CTAS", "VRSK", "EXC", "XEL", "CCEP", "LULU", "DDOG", "CSGP", "IDXX", "ON",
    "ZS", "TTWO", "ANSS", "DXCM", "GEHC", "BIIB", "MCHP", "WBD", "GFS", "CDW",
    "ARM", "MRNA", "ILMN", "WBA", "MDB", "SMCI", "TEAM", "SIRI", "DLTR", "FANG",
})

# 미국 대표 ETF 큐레이션 (티커, 한글명). 초보자에게 익숙한 광범위·섹터 대표 ETF.
US_ETF_SEED: tuple[tuple[str, str], ...] = (
    ("SPY", "S&P 500 ETF (SPY)"),
    ("VOO", "뱅가드 S&P 500 ETF (VOO)"),
    ("IVV", "iShares S&P 500 ETF (IVV)"),
    ("QQQ", "나스닥100 ETF (QQQ)"),
    ("VTI", "미국 전체주식 ETF (VTI)"),
    ("DIA", "다우존스 ETF (DIA)"),
    ("IWM", "러셀2000 ETF (IWM)"),
    ("SCHD", "미국 배당주 ETF (SCHD)"),
    ("VYM", "뱅가드 고배당 ETF (VYM)"),
    ("JEPI", "JPM 프리미엄 인컴 ETF (JEPI)"),
    ("SOXX", "반도체 ETF (SOXX)"),
    ("SMH", "반도체 ETF (SMH)"),
    ("XLK", "기술섹터 ETF (XLK)"),
    ("XLF", "금융섹터 ETF (XLF)"),
    ("XLE", "에너지섹터 ETF (XLE)"),
    ("GLD", "금 ETF (GLD)"),
    ("AGG", "미국 종합채권 ETF (AGG)"),
    ("ARKK", "ARK 혁신 ETF (ARKK)"),
)


def _resolve_sector_id(
    sector_name: str | None, gics_to_sector_id: dict[str, int]
) -> int | None:
    """GICS 영문 섹터명 → gics_code → sector_id. 미매핑/None이면 NULL."""
    gics = US_GICS_SECTOR_TO_CODE.get((sector_name or "").strip())
    return gics_to_sector_id.get(gics) if gics else None


def _record(
    stock_code: str, name_ko: str, name_en: str, market: str, sector_id: int | None
) -> dict[str, object]:
    """해외 CompanyEntity upsert 레코드. corp_code=None이라 DART 수집에서 제외된다."""
    return {
        "stock_code": stock_code,
        "name_ko": name_ko,
        "name_en": name_en,
        "corp_code": None,
        "market": market,
        "sector_id": sector_id,
        "aliases": [],
        "is_active": True,
    }


def build_overseas_records(
    sp500: list[tuple[str, str, str]],
    nasdaq_name_map: dict[str, str],
    etf_seed: tuple[tuple[str, str], ...],
    gics_to_sector_id: dict[str, int],
) -> list[dict[str, object]]:
    """소스별 종목을 버킷 우선순위(ETF > NASDAQ > SP500)로 서로소 배정해 레코드 생성.

    Args:
        sp500: FDR S&P500 리스팅 (ticker, 영문명, GICS 영문 섹터명) 목록.
        nasdaq_name_map: NASDAQ 전체 리스팅의 ticker→영문명 (S&P500 미포함 NASDAQ-100 이름 보강용).
        etf_seed: 큐레이션 ETF (ticker, 한글명) 목록.
        gics_to_sector_id: gics_code → sector_id.

    섹터는 S&P500 리스팅 기준으로만 매핑한다(NASDAQ 전체 리스팅엔 GICS 섹터가 불안정).
    """
    sp500_name = {ticker: name for ticker, name, _ in sp500}
    sp500_sector = {ticker: sector for ticker, _, sector in sp500}

    records: dict[str, dict[str, object]] = {}

    # 1) ETF — 최우선 버킷
    for ticker, name_ko in etf_seed:
        records[ticker] = _record(ticker, name_ko, ticker, "US_ETF", None)

    # 2) NASDAQ-100 — 상장 거래소 기준 우선. 이름은 S&P500→NASDAQ 리스팅→티커 순 폴백.
    for ticker in sorted(NASDAQ_100_TICKERS):
        if ticker in records:
            continue
        name = sp500_name.get(ticker) or nasdaq_name_map.get(ticker) or ticker
        sector_id = _resolve_sector_id(sp500_sector.get(ticker), gics_to_sector_id)
        records[ticker] = _record(ticker, name, name, "NASDAQ", sector_id)

    # 3) S&P500 잔여 — NASDAQ-100에 안 든 NYSE 대형주
    for ticker, name, sector_name in sp500:
        if ticker in records:
            continue
        sector_id = _resolve_sector_id(sector_name, gics_to_sector_id)
        records[ticker] = _record(ticker, name, name, "SP500", sector_id)

    return list(records.values())


def _fetch_sp500() -> list[tuple[str, str, str]]:
    """FDR S&P500 리스팅 → (ticker, 영문명, GICS 영문 섹터명). 동기 — to_thread로 호출."""
    import FinanceDataReader as fdr

    df = fdr.StockListing("S&P500")
    rows: list[tuple[str, str, str]] = []
    for record in df.to_dict("records"):
        ticker = str(record.get("Symbol") or "").strip()
        if not ticker:
            continue
        name = str(record.get("Name") or ticker).strip()
        sector = str(record.get("Sector") or "").strip()
        rows.append((ticker, name, sector))
    return rows


def _fetch_nasdaq_name_map() -> dict[str, str]:
    """FDR NASDAQ 전체 리스팅 → {ticker: 영문명}. 동기 — to_thread로 호출."""
    import FinanceDataReader as fdr

    df = fdr.StockListing("NASDAQ")
    name_map: dict[str, str] = {}
    for record in df.to_dict("records"):
        ticker = str(record.get("Symbol") or "").strip()
        if not ticker:
            continue
        name_map[ticker] = str(record.get("Name") or ticker).strip()
    return name_map


async def sync_overseas_companies(db: AsyncSession) -> dict[str, int]:
    """해외 종목 유니버스를 company_entities에 동기화(upsert).

    Returns:
        {"total": 적재 종목 수, "US_ETF"/"NASDAQ"/"SP500": 버킷별 수}
    """
    logger.info("FDR S&P500 / NASDAQ 리스팅 조회 중...")
    sp500, nasdaq_name_map = await asyncio.gather(
        asyncio.to_thread(_fetch_sp500),
        asyncio.to_thread(_fetch_nasdaq_name_map),
    )
    logger.info("S&P500 %d종목 · NASDAQ 리스팅 %d종목", len(sp500), len(nasdaq_name_map))

    sector_rows = (await db.execute(select(Sector.id, Sector.gics_code))).all()
    gics_to_sector_id = {gics: sid for sid, gics in sector_rows}

    records = build_overseas_records(sp500, nasdaq_name_map, US_ETF_SEED, gics_to_sector_id)
    if not records:
        logger.warning("해외 적재 레코드 0건 — FDR 응답/컬럼명 확인 필요")
        return {"total": 0}

    BATCH = 500
    for i in range(0, len(records), BATCH):
        batch = records[i: i + BATCH]
        stmt = pg_insert(CompanyEntity).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["stock_code"],
            set_={
                "name_ko": stmt.excluded.name_ko,
                "name_en": stmt.excluded.name_en,
                "market": stmt.excluded.market,
                "sector_id": stmt.excluded.sector_id,
                "is_active": stmt.excluded.is_active,
            },
        )
        await db.execute(stmt)
        await db.commit()

    counts: dict[str, int] = {"total": len(records)}
    for record in records:
        market = str(record["market"])
        counts[market] = counts.get(market, 0) + 1
    logger.info("해외 적재 완료: %s", counts)
    return counts
