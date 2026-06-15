# 장독대 Airflow 이미지 (설계 00 §12.3)
#
# Airflow 코어는 SQLAlchemy 1.4, 장독대 앱은 SQLAlchemy 2.0을 쓰므로 한 환경에 못 섞는다.
# → 앱 의존성을 별도 venv(/home/airflow/jangdokdae-venv)에 격리하고, DAG는
#   ExternalPythonOperator로 이 venv의 python을 호출한다. Airflow 코어 환경은 베이스 그대로.
ARG AIRFLOW_VERSION=3.0.0
FROM apache/airflow:${AIRFLOW_VERSION}-python3.12

# hdbscan 등 네이티브 빌드용 컴파일러 (arm64 휠이 없을 때 대비)
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ \
    && rm -rf /var/lib/apt/lists/*
USER airflow

# 앱 전용 venv — 앱 의존성(SQLA 2.0 등)을 Airflow 코어(1.4)와 분리
COPY requirements-airflow.txt /requirements-airflow.txt
RUN python -m venv /home/airflow/jangdokdae-venv \
    && /home/airflow/jangdokdae-venv/bin/pip install --no-cache-dir --upgrade pip \
    && /home/airflow/jangdokdae-venv/bin/pip install --no-cache-dir -r /requirements-airflow.txt
