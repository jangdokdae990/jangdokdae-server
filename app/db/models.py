from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class News(Base):
    __tablename__ = "news"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    source = Column(String(100), nullable=False)
    url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class UserInterest(Base):
    __tablename__ = "user_interests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)
    symbol = Column(String(50), nullable=False)  # 종목 코드
    sector = Column(String(100), nullable=True)  # 섹터
    created_at = Column(DateTime, default=datetime.utcnow)
