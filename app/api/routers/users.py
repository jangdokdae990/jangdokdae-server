"""사용자 라우터 — 마이페이지 프로필 조회 (인증 필수).

관심 수정은 별도 라우터가 없고 온보딩 제출 API(POST /onboarding/interests)를 재사용한다.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.auth import InterestSummary
from app.api.schemas.user import UserProfileResponse
from app.core.errors import AuthError
from app.core.security import get_current_user
from app.db.base import get_db
from app.db.queries import get_user_by_id, get_user_interests

router = APIRouter(prefix="/user", tags=["user"])


@router.get("/profile", response_model=UserProfileResponse)
async def get_profile(
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserProfileResponse:
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise AuthError("사용자를 찾을 수 없습니다")
    interests = await get_user_interests(db, user_id)
    return UserProfileResponse(
        id=user.id,
        provider=user.provider,
        email=user.email,
        nickname=user.nickname,
        profile_image_url=user.profile_image_url,
        onboarding_completed=user.onboarding_completed_at is not None,
        interests=InterestSummary(**interests),
    )
