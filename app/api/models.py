from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr


class UserBase(BaseModel):
    email: EmailStr
    username: str


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class NewsBase(BaseModel):
    title: str
    content: str
    source: str


class NewsResponse(NewsBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class InterestCreate(BaseModel):
    symbol: str
    sector: Optional[str] = None


class InterestResponse(BaseModel):
    id: int
    user_id: int
    symbol: str
    sector: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
