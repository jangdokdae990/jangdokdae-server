"""시각 변환 공통 함수."""

from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def to_naive_kst(dt: datetime) -> datetime:
    """datetime을 timezone 없는 한국 시각(KST 벽시계)으로 변환. naive 입력은 KST로 간주."""
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(KST).replace(tzinfo=None)
