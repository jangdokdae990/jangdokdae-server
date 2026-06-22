"""SPOF 전환 메트릭 계기판 (설계 00 §11.5) — 단일 호스트 docker-compose의 한계 임계.

docker-compose(LocalExecutor)는 데모·소규모 운영을 한 구성으로 커버하되 단일 호스트라는
한계가 또렷하다. 여기 임계는 "지금 막아야 할 결함"이 아니라 측정값이 닿으면 Celery/K8s
Executor·Composer로 승격할 **전환 시점**을 알려주는 계기판이다(초기 추정값, 운영 데이터로 교정).

측정 출처가 다르다 — 일 수집량만 DB에서 직접 잰다(`measure_daily_volume`). 세션 배치 소요·월
수동 개입은 Airflow run 이력·운영 로그에 있어 호출부가 주입한다. 판정(`evaluate_transition_signals`)
은 순수 함수라 임계 경계를 테스트로 고정하고, 모니터링 DAG·운영 스크립트가 조립해 `log_report`로
끌어올린다.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.queries import count_recent_news
from utils.dates import now_kst

logger = logging.getLogger(__name__)


@dataclass
class TransitionSignal:
    """전환 신호 1종 — 측정값과 임계, 초과 여부."""

    name: str
    measured: float
    threshold: float
    breached: bool
    detail: str


@dataclass
class SpofReport:
    """SPOF 계기판 리포트 — 신호 묶음과 전환 판단."""

    signals: list[TransitionSignal]

    @property
    def should_transition(self) -> bool:
        """하나라도 임계에 닿으면 전환 검토 신호를 올린다."""
        return any(s.breached for s in self.signals)

    @property
    def breached(self) -> list[TransitionSignal]:
        return [s for s in self.signals if s.breached]


def evaluate_transition_signals(
    daily_volume: int,
    batch_duration_seconds: float,
    session_interval_seconds: float,
    monthly_manual_interventions: int,
) -> SpofReport:
    """측정값을 §11.5 임계와 대조해 전환 계기판 리포트를 만든다(순수 함수).

    - 일 수집량 ≥ 임계 → 단일 머신 직렬 처리(백필·대량 재처리) 부담
    - 세션 배치 소요 ÷ 세션 간격 ≥ 비율 → 소요가 간격을 잠식, 스케일아웃 압박
    - 월 수동 개입 ≥ 임계 → 무중단 운영 한계

    세션 간격이 0 이하면(측정 불가) 비율 신호는 0으로 둬 오탐을 피한다.
    """
    ratio = (
        batch_duration_seconds / session_interval_seconds
        if session_interval_seconds > 0
        else 0.0
    )
    signals = [
        TransitionSignal(
            name="daily_volume",
            measured=float(daily_volume),
            threshold=float(settings.spof_daily_volume_threshold),
            breached=daily_volume >= settings.spof_daily_volume_threshold,
            detail="일 수집량 — 단일 머신 직렬 처리(백필·대량 재처리) 부담",
        ),
        TransitionSignal(
            name="batch_duration_ratio",
            measured=round(ratio, 3),
            threshold=settings.spof_batch_duration_ratio,
            breached=ratio >= settings.spof_batch_duration_ratio,
            detail="세션 배치 소요÷세션 간격 — 소요가 간격을 잠식하면 스케일아웃 필요",
        ),
        TransitionSignal(
            name="monthly_manual_interventions",
            measured=float(monthly_manual_interventions),
            threshold=float(settings.spof_monthly_manual_interventions),
            breached=monthly_manual_interventions >= settings.spof_monthly_manual_interventions,
            detail="월 수동 개입 — 무중단 운영 한계",
        ),
    ]
    return SpofReport(signals=signals)


async def measure_daily_volume(db: AsyncSession, window_hours: int = 24) -> int:
    """최근 window_hours 동안 수집된 news 행 수 — DB에서 직접 재는 유일한 신호."""
    since = now_kst() - timedelta(hours=window_hours)
    return await count_recent_news(db, since)


def log_report(report: SpofReport) -> None:
    """계기판 리포트를 로그로 끌어올린다 — 초과 신호는 warning, 정상이면 info."""
    if report.should_transition:
        names = ", ".join(
            f"{s.name}={s.measured}≥{s.threshold}" for s in report.breached
        )
        logger.warning("SPOF 전환 신호 도달 — Celery/K8s·Composer 승격 검토: %s", names)
    else:
        logger.info("SPOF 계기판 정상 — 전환 신호 없음(단일 호스트 한계선 내)")
