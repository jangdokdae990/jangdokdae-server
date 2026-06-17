"""분기 보고서 수집 DAG — 분기 첫날 09:00 KST.

흐름: collect_reports >> embed_reports
사업보고서·재무는 분기 주기라 메인과 분리한다. 수집한 청크를 임베딩해 분석 단계의
기업 컨텍스트(RAG)로 제공한다.

단계 실행은 ExternalPythonOperator로 앱 전용 venv에서 돌린다.
"""

from __future__ import annotations

import pendulum
from airflow.providers.standard.operators.python import ExternalPythonOperator
from airflow.sdk import DAG
from airflow.timetables.trigger import CronTriggerTimetable

APP_PYTHON = "/home/airflow/jangdokdae-venv/bin/python"


def _collect_reports() -> None:
    import asyncio
    import sys

    sys.path.insert(0, "/opt/jangdokdae")
    from services.pipeline.company_collector import CompanyCollector

    asyncio.run(CompanyCollector().run("quarterly"))


def _embed_reports() -> None:
    import asyncio
    import sys

    sys.path.insert(0, "/opt/jangdokdae")
    from app.db.base import AsyncSessionLocal
    from services.embedder.report_embedder import ReportEmbedder

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await ReportEmbedder().embed_chunks(db)

    asyncio.run(_run())


with DAG(
    dag_id="jangdokdae_quarterly",
    # 분기 첫날(1·4·7·10월 1일) 09:00
    schedule=CronTriggerTimetable("0 9 1 1,4,7,10 *", timezone="Asia/Seoul"),
    start_date=pendulum.datetime(2026, 1, 1, tz="Asia/Seoul"),
    catchup=False,
    default_args={"retries": 2, "retry_delay": pendulum.duration(seconds=60)},
    tags=["jangdokdae", "quarterly"],
) as dag:
    collect_reports = ExternalPythonOperator(
        task_id="collect_reports",
        python=APP_PYTHON,
        python_callable=_collect_reports,
        expect_airflow=False,  # venv엔 airflow 미설치(앱 의존성만)
    )
    embed_reports = ExternalPythonOperator(
        task_id="embed_reports",
        python=APP_PYTHON,
        python_callable=_embed_reports,
        expect_airflow=False,
    )
    collect_reports >> embed_reports
