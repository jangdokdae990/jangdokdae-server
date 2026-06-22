"""시각 변환 공통 함수."""

from datetime import datetime, time
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")

# 장 운영 시간대 경계(KST 벽시계) — market_session 라벨 분류용
_MARKET_OPEN = time(9, 0)     # 오전장 시작
_LUNCH_SPLIT = time(12, 0)    # 오전장/오후장 경계
_MARKET_CLOSE = time(15, 30)  # 정규장 마감


def to_naive_kst(dt: datetime) -> datetime:
    """datetime을 timezone 없는 한국 시각(KST 벽시계)으로 변환. naive 입력은 KST로 간주."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(KST).replace(tzinfo=None)


def now_kst() -> datetime:
    """현재 시각을 timezone 없는 한국 시각(KST naive)으로 반환. DB 저장값과 동일 기준."""
    return datetime.now(KST).replace(tzinfo=None)


def market_session(dt: datetime) -> str:
    """KST 벽시계 기준 시각을 4개 장 운영 시간대 라벨로 분류한다.

    보고·로그용 식별자이며 수집 동작은 가르지 않는다. aware 입력은 KST로 변환,
    naive 입력은 KST 벽시계로 간주한다(to_naive_kst):
        premarket   00:00~09:00  장 시작 전
        morning     09:00~12:00  오전장
        afternoon   12:00~15:30  오후장
        afterhours  15:30~24:00  장 마감 후
    """
    t = to_naive_kst(dt).time()
    if t < _MARKET_OPEN:
        return "premarket"
    if t < _LUNCH_SPLIT:
        return "morning"
    if t < _MARKET_CLOSE:
        return "afternoon"
    return "afterhours"


def current_market_session() -> str:
    """현재 KST 시각의 장 운영 시간대 라벨을 반환. market_session(now_kst()) 단축형."""
    return market_session(now_kst())
