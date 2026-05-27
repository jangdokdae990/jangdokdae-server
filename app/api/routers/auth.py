from fastapi import APIRouter, HTTPException, status

from app.api.models import TokenResponse

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login(username: str, password: str):
    """
    사용자 로그인 (카카오, 구글 OAuth)
    """
    # TODO: OAuth 인증 구현
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="OAuth 인증 미구현"
    )


@router.post("/logout")
async def logout():
    """
    사용자 로그아웃
    """
    return {"message": "Successfully logged out"}


@router.post("/refresh")
async def refresh_token():
    """
    액세스 토큰 갱신
    """
    # TODO: 토큰 갱신 로직 구현
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="토큰 갱신 미구현"
    )
