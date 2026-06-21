"""온보딩 라우터 — 관심 시장·섹터·종목 제출 (인증 필수).

저장·개인화라 로그인 필수. 시장·섹터는 필수, 종목은 옵션이며 제출분으로 멱등 대체한다.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.onboarding import InterestSubmit, OnboardingResult
from app.core.errors import ValidationError
from app.core.security import get_current_user
from app.db.base import get_db
from app.db.queries import (
    get_active_company_ids,
    get_active_market_ids,
    get_existing_sector_ids,
    replace_user_interests,
)

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


@router.post("/interests", response_model=OnboardingResult)
async def submit_interests(
    payload: InterestSubmit,
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OnboardingResult:
    # 존재·활성 검증 — 잘못된 id는 FK 위반(500) 대신 422로 명확히 거른다.
    # (같은 세션은 동시 쿼리가 불가하므로 순차 실행이 맞다.)
    validations = (
        (payload.market_ids, get_active_market_ids, "시장"),
        (payload.sector_ids, get_existing_sector_ids, "섹터"),
        (payload.company_ids, get_active_company_ids, "종목"),
    )
    for ids, fetch_valid_ids, label in validations:
        if set(ids) - await fetch_valid_ids(db, ids):
            raise ValidationError(f"유효하지 않은 {label} id가 포함돼 있습니다")

    try:
        await replace_user_interests(
            db, user_id, payload.market_ids, payload.sector_ids, payload.company_ids
        )
    except IntegrityError as exc:
        # 검증~삽입 사이에 대상이 비활성/삭제된 race(TOCTOU) → FK 위반. 500 대신 422.
        await db.rollback()
        raise ValidationError(
            "관심 대상이 변경되어 저장하지 못했습니다. 다시 시도해 주세요"
        ) from exc
    return OnboardingResult(status="completed")
