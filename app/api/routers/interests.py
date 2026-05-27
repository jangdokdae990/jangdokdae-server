from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.models import InterestCreate, InterestResponse
from app.db.database import get_db
from app.db.queries import add_user_interest, get_user_interests

router = APIRouter()


@router.get("/", response_model=list[InterestResponse])
async def get_interests(db: Session = Depends(get_db)):
    """현재 사용자의 관심 종목/섹터 목록 조회"""
    # TODO: 현재 로그인 사용자 ID 추출 (JWT)
    user_id = 1
    return get_user_interests(db, user_id)


@router.post("/", response_model=InterestResponse, status_code=status.HTTP_201_CREATED)
async def add_interest(interest: InterestCreate, db: Session = Depends(get_db)):
    """관심 종목/섹터 추가"""
    # TODO: 현재 로그인 사용자 ID 추출 (JWT)
    user_id = 1
    return add_user_interest(db, user_id, interest.symbol, interest.sector)


@router.delete("/{interest_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_interest(interest_id: int, db: Session = Depends(get_db)):
    """관심 종목/섹터 삭제"""
    # TODO: 현재 로그인 사용자 ID 추출 (JWT) + 권한 확인
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="관심 종목 삭제 미구현"
    )
