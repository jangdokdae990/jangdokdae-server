from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.models import NewsResponse
from app.db.database import get_db

router = APIRouter()


@router.get("/today", response_model=list[NewsResponse])
async def get_today_news(db: Session = Depends(get_db)):
    """
    오늘의 주요 시장 뉴스 조회
    """
    # TODO: 오늘의 주요 뉴스 조회 구현
    return []


@router.get("/interests", response_model=list[NewsResponse])
async def get_interest_news(db: Session = Depends(get_db)):
    """
    관심 종목/섹터별 맞춤 뉴스 조회
    """
    # TODO: 관심 종목별 뉴스 조회 구현
    return []


@router.get("/{news_id}")
async def get_news_detail(news_id: int, db: Session = Depends(get_db)):
    """
    뉴스 상세 조회 (원문 + LLM 해설)
    """
    # TODO: 뉴스 상세 정보 조회 구현
    return {}
