"""거시지표 수집기 — FinanceDataReader 환율 + 한국은행 ECOS 금리·CPI·M2.

진입점이 둘이다:
    - collect():      환율 4종(USD·JPY·EUR·CNY/KRW) — FinanceDataReader(동기→to_thread)
    - collect_ecos(): 기준금리·CPI·M2 — 한국은행 ECOS API(비동기 httpx)

두 경로 모두 지표/통화 단위로 에러를 격리한다. NaN(휴장일)·결측치 행은 스킵한다.
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date

import FinanceDataReader as fdr
import httpx

from app.config import settings
from services.collector.tools.redact import redact_secrets
from services.collector.tools.with_retry import with_retry

logger = logging.getLogger(__name__)

INDICATOR_EXCHANGE_RATE = "exchange_rate"
DEFAULT_TIMEOUT = 10.0

# (FinanceDataReader 심볼, 통화 코드)
EXCHANGE_RATES: tuple[tuple[str, str], ...] = (
    ("USD/KRW", "USD"),
    ("JPY/KRW", "JPY"),
    ("EUR/KRW", "EUR"),
    ("CNY/KRW", "CNY"),
)

ECOS_BASE_URL = "https://ecos.bok.or.kr/api"
ECOS_ROW_COUNT = 1000  # 요청 최대 행수


@dataclass(frozen=True)
class EcosIndicator:
    indicator_type: str  # MarketIndicator.indicator_type 값
    stat_code: str       # ECOS 통계표 코드
    item_code: str       # ECOS 통계항목 코드
    cycle: str           # 주기: "M"(월)·"D"(일)·"Q"(분기)·"A"(년)


# 모두 월별(M). currency는 NULL (환율이 아님)
# 주의: M2 코드는 161Y006 (구 표 101Y004는 폐지됨)
ECOS_INDICATORS: tuple[EcosIndicator, ...] = (
    EcosIndicator("interest_rate", "722Y001", "0101000", "M"),  # 한국은행 기준금리
    EcosIndicator("cpi", "901Y009", "0", "M"),                  # 소비자물가지수 총지수
    EcosIndicator("m2", "161Y006", "BBHA00", "M"),              # M2(평잔, 원계열)
)


@dataclass(frozen=True)
class CollectedIndicator:
    indicator_type: str
    currency: str | None
    value: float
    date: date

    def to_record(self) -> dict[str, object]:
        # MarketIndicator 컬럼 입력 형식
        return {
            "indicator_type": self.indicator_type,
            "currency": self.currency,
            "value": self.value,
            "date": self.date,
        }


def _ym_to_date(time_str: str) -> date:
    # ECOS 월별 TIME "202601" → 해당 월 1일
    return date(int(time_str[:4]), int(time_str[4:6]), 1)


class MacroCollector:
    def __init__(
        self,
        exchange_rates: tuple[tuple[str, str], ...] = EXCHANGE_RATES,
        ecos_indicators: tuple[EcosIndicator, ...] = ECOS_INDICATORS,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.exchange_rates = exchange_rates
        self.ecos_indicators = ecos_indicators
        self.timeout = timeout

    # ── 환율 (FinanceDataReader, 동기 → to_thread) ────────────────────────
    async def collect(self, start_date: str) -> list[CollectedIndicator]:
        """환율을 start_date(YYYY-MM-DD)부터 수집. 통화 단위 에러 격리."""
        batches = await asyncio.gather(
            *[
                asyncio.to_thread(self._fetch_rate, symbol, currency, start_date)
                for symbol, currency in self.exchange_rates
            ],
            return_exceptions=True,
        )
        indicators: list[CollectedIndicator] = []
        for (symbol, currency), batch in zip(self.exchange_rates, batches):
            if isinstance(batch, BaseException):
                logger.error("환율 수집 실패 currency=%s err=%s", currency, batch)
                continue
            indicators.extend(batch)
        return indicators

    @staticmethod
    def _fetch_rate(symbol: str, currency: str, start_date: str) -> list[CollectedIndicator]:
        # FinanceDataReader는 동기 라이브러리 → collect()에서 to_thread로 호출
        df = fdr.DataReader(symbol, start_date)
        indicators: list[CollectedIndicator] = []
        for idx, row in df.iterrows():
            close = row["Close"]
            if close is None or close != close:  # None 또는 NaN(휴장일 등) 스킵
                continue
            indicators.append(
                CollectedIndicator(
                    indicator_type=INDICATOR_EXCHANGE_RATE,
                    currency=currency,
                    value=float(close),
                    date=idx.date(),
                )
            )
        return indicators

    # ── 거시지표 (한국은행 ECOS, 비동기 httpx) ────────────────────────────
    async def collect_ecos(self, bgn_ym: str, end_ym: str) -> list[CollectedIndicator]:
        """금리·CPI·M2를 기간(YYYYMM) 동안 수집. 지표 단위 에러 격리."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            batches = await asyncio.gather(
                *[self._fetch_ecos(client, ind, bgn_ym, end_ym) for ind in self.ecos_indicators],
                return_exceptions=True,
            )
        indicators: list[CollectedIndicator] = []
        for ind, batch in zip(self.ecos_indicators, batches):
            if isinstance(batch, BaseException):
                logger.error(
                    "ECOS 수집 실패 type=%s err=%s", ind.indicator_type, redact_secrets(batch)
                )
                continue
            indicators.extend(batch)
        return indicators

    @with_retry(max_attempts=2, retry_on=httpx.TransportError)
    async def _fetch_ecos(
        self, client: httpx.AsyncClient, ind: EcosIndicator, bgn_ym: str, end_ym: str
    ) -> list[CollectedIndicator]:
        # 일시 네트워크 오류(TransportError)만 1회 더 시도해 흡수한다 —
        # 4xx/5xx·응답 비정상은 전파하여 Airflow Task 재시도/격리에 맡긴다.
        url = (
            f"{ECOS_BASE_URL}/StatisticSearch/{settings.ecos_api_key}/json/kr/1/{ECOS_ROW_COUNT}/"
            f"{ind.stat_code}/{ind.cycle}/{bgn_ym}/{end_ym}/{ind.item_code}"
        )
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()
        if "StatisticSearch" not in data:
            logger.warning(
                "ECOS 응답 비정상 type=%s code=%s",
                ind.indicator_type,
                data.get("RESULT", {}).get("CODE"),
            )
            return []
        indicators: list[CollectedIndicator] = []
        for row in data["StatisticSearch"].get("row", []):
            value = row.get("DATA_VALUE")
            if not value:  # 결측치 스킵
                continue
            indicators.append(
                CollectedIndicator(
                    indicator_type=ind.indicator_type,
                    currency=None,
                    value=float(value),
                    date=_ym_to_date(row["TIME"]),
                )
            )
        return indicators
