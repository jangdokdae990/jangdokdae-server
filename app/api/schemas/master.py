"""마스터 조회(시장·섹터·종목) 응답 스키마."""

from pydantic import BaseModel

from app.api.schemas.common import ORMSchema


class MarketOut(ORMSchema):
    id: int
    code: str
    name_ko: str
    name_en: str
    description: str | None
    tags: list[str]


class SectorOut(ORMSchema):
    id: int
    name_ko: str
    name_en: str
    wics_code: str
    gics_code: str


class CompanyOut(ORMSchema):
    id: int
    stock_code: str
    name_ko: str
    market: str
    sector_id: int | None


class CompanyPage(BaseModel):
    """종목 커서 페이지 — next_cursor가 None이면 마지막 페이지."""

    items: list[CompanyOut]
    next_cursor: int | None
