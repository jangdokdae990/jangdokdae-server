"""거시지표 수집 DAG — 매월 1일 16:00 KST.

거시지표(ECOS: 금리·CPI·M2)는 월 주기라 메인 파이프라인과 분리한다. 적재만 하고, 다음
메인 run의 embed·analyze가 흡수한다.

단계 실행은 ExternalPythonOperator로 앱 전용 venv에서 돌린다.
"""

from __future__ import annotations

import pendulum
from airflow.providers.standard.operators.python import ExternalPythonOperator
from airflow.sdk import DAG
from airflow.timetables.trigger import CronTriggerTimetable

APP_PYTHON = "/home/airflow/jangdokdae-venv/bin/python"


def _collect_macro() -> None:
    import asyncio
    import sys

    sys.path.insert(0, "/opt/jangdokdae")
    from services.pipeline.company_collector import CompanyCollector

    asyncio.run(CompanyCollector().run("macro"))


with DAG(
    dag_id="jangdokdae_macro",
    schedule=CronTriggerTimetable("0 16 1 * *", timezone="Asia/Seoul"),  # 매월 1일 16:00
    start_date=pendulum.datetime(2026, 1, 1, tz="Asia/Seoul"),
    catchup=False,
    default_args={"retries": 2, "retry_delay": pendulum.duration(seconds=60)},
    tags=["jangdokdae", "macro"],
) as dag:
    collect_macro = ExternalPythonOperator(
        task_id="collect_macro",
        python=APP_PYTHON,
        python_callable=_collect_macro,
        expect_airflow=False,  # venv엔 airflow 미설치(앱 의존성만)
    )
