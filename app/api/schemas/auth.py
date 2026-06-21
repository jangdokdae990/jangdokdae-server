"""인증 도메인 요청·응답 스키마."""

from pydantic import BaseModel


class InterestSummary(BaseModel):
    market_ids: list[int]
    sector_ids: list[int]
    company_ids: list[int]


class MeResponse(BaseModel):
    """현재 로그인 사용자 + 온보딩 상태 + 관심 요약 (/auth/me)."""

    id: int
    provider: str
    email: str | None
    nickname: str | None
    profile_image_url: str | None
    onboarding_completed: bool
    interests: InterestSummary
