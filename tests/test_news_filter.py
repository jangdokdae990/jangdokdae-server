# 단독 실행: uv run pytest tests/test_news_filter.py -s
"""수집 제외 필터(news_filter) 단위 테스트 — 비기사성 뉴스 판정 정확도.

검증 포인트:
- 제목 괄호 태그를 괄호 종류와 무관하게 추출해 키워드셋과 정확 일치로 판정한다.
- 괄호 변형(<부고>·【부고】)·내부 공백·대소문자 변형까지 잡는다.
- 정상 기사 태그([단독]·[종합] 등)와 부분 일치 함정("[발표]" vs 키워드 '표')은 통과시킨다.
- 본문/요약 면책 문구(AI 자동요약)는 위치와 무관하게 잡는다.
"""

import pytest

from services.collector.news_filter import is_excluded


@pytest.mark.parametrize(
    "title",
    [
        "[부고] 최종원(한국예탁결제원 수석위원)씨 부친상",
        "<부고> 홍길동씨 별세",
        "【부고】 김모씨 빈소",
        "[AI 카드뉴스] 한눈에 보는 오늘 증시",
        "[ 카드뉴스 ] 공백이 있어도 잡힌다",
        "[포토] 코스피 전광판",
        "[표] 주요 종목 등락률",
        "(인사) 삼성전자 임원 인사",
    ],
)
def test_excluded_title_tags(title):
    """비기사 카테고리 태그(괄호 변형·공백 포함)는 제외 대상이다."""
    assert is_excluded(title) is True


@pytest.mark.parametrize(
    "title",
    [
        "코스피 2600선 회복…외국인 순매수",
        "[단독] 삼성, 신규 투자 발표",  # 정상 기사 태그는 보존
        "[종합] 한은 기준금리 동결",
        "[속보] 환율 급등",
        "[발표] 정부 부동산 대책",  # 태그 '발표' ≠ 키워드 '표' (부분 일치 함정)
        "[특징주] 에코프로 강세",
    ],
)
def test_normal_news_not_excluded(title):
    """일반 기사·정상 태그는 제외하지 않는다(오탐 방지)."""
    assert is_excluded(title) is False


def test_body_marker_excluded_regardless_of_position():
    """제목/요약 어디든 AI 자동요약 면책 문구가 있으면 제외 대상."""
    summary = "본문 일부… AI가 자동 생성한 요약으로 정확하지 않을 수 있어요."
    assert is_excluded("삼성전자 3분기 실적", summary) is True


def test_ai_generated_column_excluded_by_summary_marker():
    """기사 전체가 AI 생성물인 칼럼(엠블록레터)은 RSS 요약의 AI 인턴 인사말로 제외한다."""
    title = "SEC 혁신 면제 임박...토큰화 주식 시대 본격 열린다[엠블록레터]"
    summary = "안녕하세요 엠블록레터의 AI 인턴입니다. 미국 SEC가 토큰화 주식 거래를 허용한다."
    assert is_excluded(title, summary) is True


def test_no_tag_normal_title_not_excluded():
    """괄호 태그가 없는 평범한 제목은 통과한다."""
    assert is_excluded("증시 마감 시황", "오늘 증시는 상승 마감했다.") is False
