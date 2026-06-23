"""이벤트 기반 클러스터링 DAG — 임베딩 완료(EMBED_ASSET) 시 트리거.

세션 배치 DAG(jangdokdae_pipeline)의 embed Task가 EMBED_ASSET을 produce하면 이 DAG가 깨어나
근접중복 제거 + 최근 14일 윈도우 전체 재클러스터링 + cluster id 승계 후 분석(analyze)까지 잇는다
(고정 cron 없음). 분석은 클러스터링 출력에 의존하므로 같은 DAG에서 cluster >> analyze로 실행한다.

max_active_runs=1 — 윈도우 전체 재계산이라 동시 실행되면 서로의 클러스터를 덮어쓴다.
Airflow 코어↔앱 의존성 분리를 위해 ExternalPythonOperator(앱 전용 venv)로 실행한다.
"""

from __future__ import annotations

import pendulum
from airflow.providers.standard.operators.python import ExternalPythonOperator
from airflow.sdk import DAG
from assets import EMBED_ASSET

# 앱 의존성(SQLA 2.0)을 격리한 venv — Airflow 코어(1.4)와 분리.
APP_PYTHON = "/home/airflow/jangdokdae-venv/bin/python"


def _cluster() -> None:
    import asyncio
    import sys

    sys.path.insert(0, "/opt/jangdokdae")
    from app.db.base import AsyncSessionLocal
    from services.pipeline.embedding_clusterer import EmbeddingClusterer

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await EmbeddingClusterer().cluster(db)  # dedup + 14일 윈도우 재클러스터링 + id 승계

    asyncio.run(_run())


def _analyze() -> None:
    import asyncio
    import sys

    sys.path.insert(0, "/opt/jangdokdae")
    from app.db.base import AsyncSessionLocal
    from services.pipeline.news_analyzer import NewsAnalyzer

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await NewsAnalyzer().run(db)

    asyncio.run(_run())


with DAG(
    dag_id="jangdokdae_clustering",
    schedule=[EMBED_ASSET],  # 임베딩 완료(데이터 도착) 이벤트로 트리거 — 고정 cron 없음
    start_date=pendulum.datetime(2026, 1, 1, tz="Asia/Seoul"),
    catchup=False,
    max_active_runs=1,  # 윈도우 전체 재계산 — 동시 실행 금지
    default_args={"retries": 2, "retry_delay": pendulum.duration(seconds=60)},
    tags=["jangdokdae", "clustering"],
) as dag:
    cluster = ExternalPythonOperator(
        task_id="cluster",
        python=APP_PYTHON,
        python_callable=_cluster,
        expect_airflow=False,
    )
    # 분석(분류·콘텐츠 생성, →10) — LangGraph 단일 에이전트를 앱 venv에서 호출.
    analyze = ExternalPythonOperator(
        task_id="analyze",
        python=APP_PYTHON,
        python_callable=_analyze,
        expect_airflow=False,
    )
    cluster >> analyze
