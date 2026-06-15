"""메인 파이프라인 DAG — 평일 09:00·15:30 KST, 1 run = 전체 완주(설계 00 §7.1·§8).

흐름: [collect_news, collect_company] >> embed_cluster (분석 06은 미구현 TODO).
각 Task가 단계를 직접 호출하고, 단계 간 데이터는 공유 DB(Neon) 상태로만 핸드오프한다(§6).

Airflow 코어(SQLAlchemy 1.4)와 장독대 앱(SQLAlchemy 2.0)은 의존성이 충돌하므로, 단계
실행은 ExternalPythonOperator로 앱 전용 venv(SQLA 2.0)에서 돌린다(설계 00 §12.3). callable은
venv에서 직렬화 실행되므로 self-contained(내부 import + sys.path 보강)로 작성한다.

09:00 run은 morning, 15:30 run은 afternoon 공시를 수집한다 — 두 트리거를 한 DAG에
묶었으므로 logical_date(KST)로 schedule을 갈라 op_args(Jinja)로 넘긴다.
"""

from __future__ import annotations

import pendulum
from airflow.providers.standard.operators.python import ExternalPythonOperator
from airflow.sdk import DAG
from airflow.timetables.trigger import MultipleCronTriggerTimetable

# 앱 의존성(SQLA 2.0)을 격리한 venv — Airflow 코어(1.4)와 분리(설계 00 §12.3)
APP_PYTHON = "/home/airflow/jangdokdae-venv/bin/python"
# 09:00 run=morning, 15:30 run=afternoon (Jinja로 렌더해 op_args로 전달)
SCHEDULE_ARG = (
    "{{ 'morning' if data_interval_start.in_timezone('Asia/Seoul').hour < 12 "
    "else 'afternoon' }}"
)


def _collect_news(schedule: str) -> None:
    import asyncio
    import sys

    sys.path.insert(0, "/opt/jangdokdae")
    from app.db.base import AsyncSessionLocal
    from services.pipeline.news_collector import NewsCollector

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await NewsCollector().run(db, schedule)

    asyncio.run(_run())


def _collect_company(schedule: str) -> None:
    import asyncio
    import sys

    sys.path.insert(0, "/opt/jangdokdae")
    from services.pipeline.company_collector import CompanyCollector

    asyncio.run(CompanyCollector().run(schedule))


def _embed_cluster() -> None:
    import asyncio
    import sys

    sys.path.insert(0, "/opt/jangdokdae")
    from app.db.base import AsyncSessionLocal
    from services.pipeline.embedding_clusterer import EmbeddingClusterer

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await EmbeddingClusterer().run(db)

    asyncio.run(_run())


with DAG(
    dag_id="jangdokdae_pipeline",
    # 평일 09:00·15:30 KST 두 트리거 — 분이 달라 단일 cron 불가, timetable로 묶는다.
    schedule=MultipleCronTriggerTimetable(
        "0 9 * * 1-5", "30 15 * * 1-5", timezone="Asia/Seoul"
    ),
    start_date=pendulum.datetime(2026, 1, 1, tz="Asia/Seoul"),
    catchup=False,  # 뉴스는 24h 창이라 과거 소급이 무의미
    default_args={"retries": 2, "retry_delay": pendulum.duration(seconds=60)},
    tags=["jangdokdae", "pipeline"],
) as dag:
    collect_news = ExternalPythonOperator(
        task_id="collect_news",
        python=APP_PYTHON,
        python_callable=_collect_news,
        op_args=[SCHEDULE_ARG],
        expect_airflow=False,  # venv엔 airflow 미설치(앱 의존성만)
    )
    collect_company = ExternalPythonOperator(
        task_id="collect_company",
        python=APP_PYTHON,
        python_callable=_collect_company,
        op_args=[SCHEDULE_ARG],
        expect_airflow=False,
    )
    embed_cluster = ExternalPythonOperator(
        task_id="embed_cluster",
        python=APP_PYTHON,
        python_callable=_embed_cluster,
        expect_airflow=False,
    )
    # TODO: analyze Task — NewsAnalysisAgent(06, L2) 구현 후 embed_cluster >> analyze 연결
    [collect_news, collect_company] >> embed_cluster
