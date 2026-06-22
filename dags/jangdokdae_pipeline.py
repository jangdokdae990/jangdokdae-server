"""세션 배치 DAG — 매일(주말 포함) 00:00·09:00·12:00·15:30 KST 수집·임베딩.

흐름: [collect_news, collect_company] >> embed. embed는 EMBED_ASSET을 produce하고, 클러스터링·분석은
별도 이벤트 기반 DAG(jangdokdae_clustering: cluster >> analyze)가 그 Asset을 consume해 수행한다
(수집 시점 임베딩 / 이벤트 기반 재클러스터링·분석 분리). 데이터는 공유 DB(Neon)로만 핸드오프.

Airflow 코어(SQLAlchemy 1.4)와 앱(SQLAlchemy 2.0)이 충돌하므로 단계 실행은
ExternalPythonOperator로 앱 전용 venv에서 돌린다. callable은 venv에서 직렬화 실행되므로
self-contained(내부 import + sys.path 보강)로 작성한다.

각 collect callable이 실행 시점 KST 벽시계를 장 운영 시간대 라벨
(premarket/morning/afternoon/afterhours)로 가른다 — 보고·로그용이며 수집 동작은 동일하다.
"""

from __future__ import annotations

import pendulum
from airflow.providers.standard.operators.python import ExternalPythonOperator
from airflow.sdk import DAG
from airflow.timetables.trigger import MultipleCronTriggerTimetable
from assets import EMBED_ASSET

# 매일(주말 포함) 장 운영 시간대 4구간 경계에 트리거 — 각 run의 트리거 시각이 해당
# 구간에 들어가 market_session 라벨(premarket/morning/afternoon/afterhours)과 자동 정합한다.
# 주말엔 장이 닫혀 있지만 야간·해외 뉴스와 공시가 이어지므로 동일 빈도로 수집한다.
MARKET_SCHEDULE = MultipleCronTriggerTimetable(
    "0 0 * * *",    # 00:00 → premarket  (장 시작 전, 야간 공시 흡수)
    "0 9 * * *",    # 09:00 → morning
    "0 12 * * *",   # 12:00 → afternoon
    "30 15 * * *",  # 15:30 → afterhours (정규장 마감 직후)
    timezone="Asia/Seoul",
)

# 앱 의존성(SQLA 2.0)을 격리한 venv — Airflow 코어(1.4)와 분리
APP_PYTHON = "/home/airflow/jangdokdae-venv/bin/python"
# 실행 시점 KST 벽시계를 장 운영 시간대(premarket/morning/afternoon/afterhours)
# 라벨로 가른다 — 보고·로그용이며 수집 동작은 동일하다. callable 내부에서 분류한다.
def _collect_news() -> None:
    import asyncio
    import sys

    sys.path.insert(0, "/opt/jangdokdae")
    from app.db.base import AsyncSessionLocal
    from services.pipeline.news_collector import NewsCollector
    from utils.dates import current_market_session

    schedule = current_market_session()

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await NewsCollector().run(db, schedule)

    asyncio.run(_run())


def _collect_company() -> None:
    import asyncio
    import sys

    sys.path.insert(0, "/opt/jangdokdae")
    from services.pipeline.company_collector import CompanyCollector
    from utils.dates import current_market_session

    schedule = current_market_session()

    asyncio.run(CompanyCollector().run(schedule))


def _embed() -> None:
    import asyncio
    import sys

    sys.path.insert(0, "/opt/jangdokdae")
    from app.db.base import AsyncSessionLocal
    from services.pipeline.embedding_clusterer import EmbeddingClusterer

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await EmbeddingClusterer().embed(db)  # 임베딩만 — 클러스터링은 Asset 트리거 DAG

    asyncio.run(_run())


with DAG(
    dag_id="jangdokdae_pipeline",
    # 매일(주말 포함) 00:00·09:00·12:00·15:30 KST 4구간 경계 트리거 (MARKET_SCHEDULE 주석 참고).
    schedule=MARKET_SCHEDULE,
    start_date=pendulum.datetime(2026, 1, 1, tz="Asia/Seoul"),
    catchup=False,  # 뉴스는 24h 창이라 과거 소급이 무의미
    default_args={"retries": 2, "retry_delay": pendulum.duration(seconds=60)},
    tags=["jangdokdae", "pipeline"],
) as dag:
    collect_news = ExternalPythonOperator(
        task_id="collect_news",
        python=APP_PYTHON,
        python_callable=_collect_news,
        expect_airflow=False,  # venv엔 airflow 미설치(앱 의존성만)
    )
    collect_company = ExternalPythonOperator(
        task_id="collect_company",
        python=APP_PYTHON,
        python_callable=_collect_company,
        expect_airflow=False,
    )
    # embed 완료 시 EMBED_ASSET을 produce → 클러스터링 DAG가 이벤트로 트리거된다.
    embed = ExternalPythonOperator(
        task_id="embed",
        python=APP_PYTHON,
        python_callable=_embed,
        expect_airflow=False,
        outlets=[EMBED_ASSET],
    )
    [collect_news, collect_company] >> embed
