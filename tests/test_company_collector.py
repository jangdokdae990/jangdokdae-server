# 단독 실행: uv run pytest tests/test_company_collector.py -s
"""company_collector 거시지표 트레일링 윈도우 회귀 테스트.

ECOS 월지표는 발표가 지연되므로 당월이 아니라 최근 N개월을 조회해야 새 달을 채울 수 있다.
연/월 경계 계산이 깨지지 않는지 고정한다.
"""

from services.pipeline.company_collector import _recent_ym_window


def test_window_within_same_year():
    assert _recent_ym_window(2026, 6, 3) == ("202603", "202606")


def test_window_crosses_year_boundary():
    assert _recent_ym_window(2026, 2, 3) == ("202511", "202602")


def test_window_january():
    assert _recent_ym_window(2026, 1, 3) == ("202510", "202601")
