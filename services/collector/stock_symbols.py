"""StockSymbol 데이터클래스 정의 — 수집기 공통 기업 식별 인터페이스.

역할:
    주가·공시·재무·사업보고서 수집기가 공유하는 (종목코드, 종목명, DART 기업코드)
    값 객체 StockSymbol을 정의한다. 수집 대상 목록 자체는 더 이상 이 파일에
    하드코딩하지 않고 company_entities 테이블에서 로드한다(tools/company_loader).

이력:
    초기에는 DOMESTIC_STOCKS 5종목을 하드코딩했으나, company_entities 테이블 도입
    후 데이터 소스가 DB로 이전됨. 남은 DOMESTIC_STOCKS/ALL_STOCKS는 테스트
    fixture 및 DB 미연결 환경의 폴백 용도로만 유지한다.
"""

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
