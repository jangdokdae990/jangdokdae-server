"""주가 수집기 — FinanceDataReader 기반 국내 일봉(OHLCV) 수집.

역할:
    추적 기업의 일별 시가·고가·저가·종가·거래량을 start_date부터 최신까지 수집한다.
    분석 파이프라인의 '보조 컨텍스트'로 쓰인다(설계 03 §1.2).

핵심 동작:
    - collect(): 종목별로 to_thread(_fetch_one)를 asyncio.gather로 병렬 실행하고
      종목 단위로 에러를 격리한다. FinanceDataReader가 동기 라이브러리이므로
      이벤트 루프를 막지 않도록 to_thread로 감싼다.
    - 결측 OHLCV 행(거래정지·데이터 누락)은 스킵한다.

경계:
    입력 = company_loader가 만든 list[StockSymbol] / 출력 = CollectedPrice.to_record()
    → save_tool.upsert_stock_prices (stock_code, date) UPSERT.
미구현:
    시가총액·외국인 보유(pykrx)와 해외 주가(yfinance)는 설계상 보조 항목으로 미수집.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date

import FinanceDataReader as fdr

from services.collector.stock_symbols import ALL_STOCKS, StockSymbol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CollectedPrice:
    stock_code: str
    name: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    date: date

    def to_record(self) -> dict[str, object]:
        # save_tool.upsert_stock_prices / StockPrice 컬럼 입력 형식
        return {
            "stock_code": self.stock_code,
            "name": self.name,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "date": self.date,
        }


class StockCollector:
    def __init__(self, symbols: list[StockSymbol] | None = None) -> None:
        self.symbols = symbols if symbols is not None else ALL_STOCKS

    async def collect(self, start_date: str) -> list[CollectedPrice]:
        """start_date(YYYY-MM-DD)부터 최신까지 각 종목 일봉 수집. 종목 단위 에러 격리."""
        batches = await asyncio.gather(
            *[asyncio.to_thread(self._fetch_one, stock, start_date) for stock in self.symbols],
            return_exceptions=True,
        )
        prices: list[CollectedPrice] = []
        for stock, batch in zip(self.symbols, batches):
            if isinstance(batch, BaseException):
                logger.error("주가 수집 실패 stock_code=%s err=%s", stock.stock_code, batch)
                continue
            prices.extend(batch)
        return prices

    @staticmethod
    def _fetch_one(stock: StockSymbol, start_date: str) -> list[CollectedPrice]:
        # FinanceDataReader는 동기 라이브러리 → collect()에서 to_thread로 호출
        df = fdr.DataReader(stock.stock_code, start_date)
        prices: list[CollectedPrice] = []
        for idx, row in df.iterrows():
            # 결측 OHLCV 행은 스킵 (거래정지·데이터 누락)
            if row[["Open", "High", "Low", "Close", "Volume"]].isna().any():
                continue
            prices.append(
                CollectedPrice(
                    stock_code=stock.stock_code,
                    name=stock.name,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                    date=idx.date(),
                )
            )
        return prices
