from sqlalchemy.orm import Session

from app.db.models import News, User, UserInterest


# User 관련 쿼리
def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()


def get_user_by_username(db: Session, username: str):
    return db.query(User).filter(User.username == username).first()


def create_user(db: Session, email: str, username: str, hashed_password: str):
    db_user = User(email=email, username=username, hashed_password=hashed_password)
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


# News 관련 쿼리
def get_news_by_id(db: Session, news_id: int):
    return db.query(News).filter(News.id == news_id).first()


def get_all_news(db: Session, skip: int = 0, limit: int = 10):
    return db.query(News).offset(skip).limit(limit).all()


def create_news(db: Session, title: str, content: str, source: str, url: str = None):
    db_news = News(title=title, content=content, source=source, url=url)
    db.add(db_news)
    db.commit()
    db.refresh(db_news)
    return db_news


# UserInterest 관련 쿼리
def get_user_interests(db: Session, user_id: int):
    return db.query(UserInterest).filter(UserInterest.user_id == user_id).all()


def add_user_interest(db: Session, user_id: int, symbol: str, sector: str = None):
    db_interest = UserInterest(user_id=user_id, symbol=symbol, sector=sector)
    db.add(db_interest)
    db.commit()
    db.refresh(db_interest)
    return db_interest
