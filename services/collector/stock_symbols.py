"""추적 대상 기업 — 소규모 대표 종목. 확장 시 코스피200 등 추가."""

from dataclasses import dataclass


@dataclass(frozen=True)
class StockSymbol:
    stock_code: str        # 종목 코드 (예: "005930")
    name: str              # 종목명 (예: "삼성전자")
    corp_code: str = ""    # DART 기업 고유번호 (공시 수집용). 빈 값이면 DART 수집 제외


DOMESTIC_STOCKS: list[StockSymbol] = [
    StockSymbol("005930", "삼성전자", "00126380"),
    StockSymbol("000660", "SK하이닉스", "00164779"),
    StockSymbol("035420", "NAVER", "00266961"),
    StockSymbol("035720", "카카오", "00258801"),
    StockSymbol("005380", "현대차", "00164742"),
]

ALL_STOCKS: list[StockSymbol] = DOMESTIC_STOCKS
