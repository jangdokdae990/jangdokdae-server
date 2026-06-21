"""마이페이지(사용자 프로필) 응답 스키마."""

from pydantic import BaseModel

from app.api.schemas.auth import InterestSummary


class UserProfileResponse(BaseModel):
    """사용자 + 관심(시장/섹터/종목) + 온보딩 상태 (/user/profile).

    투자 성향 결과(5단계)는 투자 성향 테스트 구현(노션 §9, 보류) 후 필드 추가 예정.
    """

    id: int
    provider: str
    email: str | None
    nickname: str | None
    profile_image_url: str | None
    onboarding_completed: bool
    interests: InterestSummary
