"""마이페이지(사용자 프로필) 응답 스키마."""

from datetime import datetime

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


class UserActivityItemResponse(BaseModel):
    issue_id: int
    title: str
    read_at: datetime | None
    bookmarked_at: datetime | None
    quiz_correct_count: int | None
    quiz_total_count: int | None
    quiz_completed_at: datetime | None


class UserLearningStatsResponse(BaseModel):
    read_issue_count: int
    saved_issue_count: int
    completed_quiz_count: int
    correct_quiz_count: int


class UserActivityResponse(BaseModel):
    stats: UserLearningStatsResponse
    recent_issues: list[UserActivityItemResponse]
    saved_issues: list[UserActivityItemResponse]
    quiz_records: list[UserActivityItemResponse]
