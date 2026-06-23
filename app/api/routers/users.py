"""사용자 라우터 — 마이페이지 프로필 조회 (인증 필수).

관심 수정은 별도 라우터가 없고 온보딩 제출 API(POST /onboarding/interests)를 재사용한다.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.auth import InterestSummary
from app.api.schemas.user import (
    UserActivityItemResponse,
    UserActivityResponse,
    UserLearningStatsResponse,
    UserProfileResponse,
)
from app.core.errors import AuthError
from app.core.security import get_current_user
from app.db.base import get_db
from app.db.orm_models.issue_docent import IssueDocent
from app.db.orm_models.user_issue_activity import UserIssueActivity
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


@router.get("/activity", response_model=UserActivityResponse)
async def get_activity(
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserActivityResponse:
    rows = (
        await db.execute(
            select(UserIssueActivity, IssueDocent)
            .join(IssueDocent, UserIssueActivity.issue_docent_id == IssueDocent.id)
            .where(UserIssueActivity.user_id == user_id)
            .order_by(
                UserIssueActivity.updated_at.desc().nullslast(),
                UserIssueActivity.created_at.desc(),
            )
        )
    ).all()
    items = [
        UserActivityItemResponse(
            issue_id=activity.issue_docent_id,
            title=issue.title,
            read_at=activity.read_at,
            bookmarked_at=activity.bookmarked_at,
            quiz_correct_count=activity.quiz_correct_count,
            quiz_total_count=activity.quiz_total_count,
            quiz_completed_at=activity.quiz_completed_at,
        )
        for activity, issue in rows
    ]
    return UserActivityResponse(
        stats=UserLearningStatsResponse(
            read_issue_count=sum(item.read_at is not None for item in items),
            saved_issue_count=sum(item.bookmarked_at is not None for item in items),
            completed_quiz_count=sum(item.quiz_completed_at is not None for item in items),
            correct_quiz_count=sum(item.quiz_correct_count or 0 for item in items),
        ),
        recent_issues=[item for item in items if item.read_at is not None][:10],
        saved_issues=[item for item in items if item.bookmarked_at is not None][:10],
        quiz_records=[item for item in items if item.quiz_completed_at is not None][:10],
    )
