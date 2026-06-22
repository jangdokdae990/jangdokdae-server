"""분석 에이전트 LangGraph State (설계 10 §8).

이슈 1건이 classify → enrich → generate를 거치며 채워지는 상태. fetch·persist는 DB 경계라
오케스트레이터(NewsAnalyzer)가 그래프 밖에서 담당한다. enrich 노드는 DB 조회가 필요해 db를
상태로 받는다(인메모리 전달, 체크포인터 미사용).
"""

from __future__ import annotations

from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from services.analyzer.schemas import ClassificationResult, ContentResult, Issue


class AnalysisState(TypedDict, total=False):
    issue: Issue  # 입력 — 대표 기사 본문 + 서브 헤드라인
    db: AsyncSession  # 입력 — enrich 노드의 key 조회용 세션
    classification: ClassificationResult  # classify 노드 산출
    source_insufficient: bool  # classify 노드 산출 — 대표 기사 본문이 임계 미만(생성 건너뜀)
    enrichment: dict  # enrich 노드 산출(OPINION 현재가 등, 없으면 {})
    content: ContentResult  # generate 노드 산출
    generation_review: bool  # generate 노드 산출 — OPINION 1단 가드 최종 실패 시 True
