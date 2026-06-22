"""마스터 조회 라우터 — 온보딩용 시장·섹터·종목 목록 (guest 허용).

저장·개인화가 아닌 읽기 전용이라 비로그인도 열람 가능(get_current_user_optional).
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.master import CompanyOut, CompanyPage, MarketOut, SectorOut
from app.core.security import get_current_user_optional
from app.db.base import get_db
from app.db.queries import (
    get_active_markets,
    get_all_sectors,
    get_sector_industry_groups,
    search_companies,
)

router = APIRouter(tags=["masters"])

_COMPANY_PAGE_DEFAULT = 20
_COMPANY_PAGE_MAX = 100


@router.get("/markets", response_model=list[MarketOut])
async def list_markets(
    db: AsyncSession = Depends(get_db),
    _: int | None = Depends(get_current_user_optional),
) -> list[MarketOut]:
    markets = await get_active_markets(db)
    return [MarketOut.model_validate(market) for market in markets]


@router.get("/sectors", response_model=list[SectorOut])
async def list_sectors(
    db: AsyncSession = Depends(get_db),
    _: int | None = Depends(get_current_user_optional),
) -> list[SectorOut]:
    sectors = await get_all_sectors(db)
    groups = await get_sector_industry_groups(db)
    return [
        SectorOut(
            id=sector.id,
            name_ko=sector.name_ko,
            name_en=sector.name_en,
            wics_code=sector.wics_code,
            gics_code=sector.gics_code,
            industry_groups=groups.get(sector.id, []),
        )
        for sector in sectors
    ]


@router.get("/companies", response_model=CompanyPage)
async def list_companies(
    db: AsyncSession = Depends(get_db),
    _: int | None = Depends(get_current_user_optional),
    sector: int | None = Query(default=None, description="섹터 id 필터"),
    market: str | None = Query(
        default=None, description="시장 코드. 콤마구분 다중 선택 가능(예: NASDAQ,SP500)"
    ),
    q: str | None = Query(default=None, description="종목명·코드 검색"),
    limit: int = Query(default=_COMPANY_PAGE_DEFAULT, ge=1, le=_COMPANY_PAGE_MAX),
    cursor: int | None = Query(default=None, description="직전 페이지 마지막 id"),
) -> CompanyPage:
    market_codes = (
        tuple(code for code in (c.strip() for c in market.split(",")) if code)
        if market
        else None
    )
    companies = await search_companies(db, sector, market_codes, q, limit, cursor)
    items = [CompanyOut.model_validate(company) for company in companies]
    # 가득 찼으면 다음 페이지 존재로 보고 마지막 id를 커서로 노출.
    next_cursor = items[-1].id if len(items) == limit else None
    return CompanyPage(items=items, next_cursor=next_cursor)
