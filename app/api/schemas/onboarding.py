"""온보딩 제출 요청·응답 스키마."""

from pydantic import BaseModel, Field


class InterestSubmit(BaseModel):
    """관심 제출 — 시장·섹터 필수(빈 배열 차단), 종목 옵션.

    시장 단계 필수 여부는 추후 확정(노션 §6). 현재는 섹션 5 계약대로 필수로 둔다.
    """

    market_ids: list[int] = Field(min_length=1)
    sector_ids: list[int] = Field(min_length=1)
    company_ids: list[int] = Field(default_factory=list)


class OnboardingResult(BaseModel):
    status: str  # "completed"
