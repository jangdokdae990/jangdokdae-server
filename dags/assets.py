"""DAG 간 공유 Airflow Asset 정의.

세션 배치 DAG(jangdokdae_pipeline)의 embed Task가 EMBED_ASSET을 produce하면, 이벤트 기반
클러스터링 DAG(jangdokdae_clustering)가 이를 consume해 트리거된다 — 고정 cron이 아니라
"임베딩 완료(데이터 도착)"가 클러스터링을 깨운다(설계 00 · TODO §6).
"""

from __future__ import annotations

from airflow.sdk import Asset

# 임베딩 완료 신호 — embed Task의 outlet, 클러스터링 DAG의 schedule.
EMBED_ASSET = Asset("jangdokdae://news/embedded")
