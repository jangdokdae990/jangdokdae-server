from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.models import UserCreate, UserResponse
from app.db.database import get_db

router = APIRouter()


@router.post("/register", response_model=UserResponse)
async def register(user: UserCreate, db: Session = Depends(get_db)):
    """
    새 사용자 가입
    """
    # TODO: 사용자 등록 로직 구현
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="사용자 등록 미구현"
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user():
    """
    현재 로그인한 사용자 정보 조회
    """
    # TODO: 현재 사용자 조회 로직 구현
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="사용자 조회 미구현"
    )


@router.put("/me")
async def update_user():
    """
    현재 사용자 정보 업데이트
    """
    # TODO: 사용자 정보 업데이트 로직 구현
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="사용자 업데이트 미구현"
    )
