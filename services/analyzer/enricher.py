"""외부 데이터 보강 (설계 08 §5, 10 §6).

09번 검증이 최대 결함(P0)으로 지적한 "데이터 보강" 중, OPINION 2단 괴리율에 필요한 **현재가 key
조회**를 먼저 구현한다(08 §3-⑥·§5-2). 나머지 frame 보강(실적 재무·악재 공시 RAG·거시 등)은 후속 PR.

OPINION 흐름: 분류의 primary 기업명 → company_entities(name→stock_code) → stock_prices(최신 종가).
어느 단계든 실패하면 빈 컨텍스트를 반환하고, 생성기는 head 명세의 honest-blank 문장으로 처리한다.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.queries import get_company_by_name, get_latest_stock_price
from services.analyzer.schemas import ClassificationResult, Issue

logger = logging.getLogger(__name__)


def _primary_company(classification: ClassificationResult) -> str | None:
    """primary 역할 기업명(없으면 첫 기업, 그것도 없으면 None)."""
    for tag in classification.company_tags:
        if tag.role == "primary":
            return tag.name
    return classification.company_tags[0].name if classification.company_tags else None


class DataEnricher:
    """frame별 추가자료 보강기. 현재는 OPINION 현재가만 구현(그 외 frame은 no-op)."""

    async def enrich(
        self, db: AsyncSession, classification: ClassificationResult, issue: Issue
    ) -> dict:
        """생성용 추가자료 컨텍스트를 반환한다. 보강 대상이 없거나 조회 실패 시 빈 dict.

        반환(OPINION 성공): {"opinion_price": {name, stock_code, close, date}}.
        """
        if classification.frame != "OPINION":
            return {}

        name = _primary_company(classification)
        if not name:
            return {}
        entity = await get_company_by_name(db, name)
        if entity is None:
            logger.info("OPINION 현재가 보강 — 엔티티 미발견 name=%s", name)
            return {}
        price = await get_latest_stock_price(db, entity.stock_code)
        if price is None:
            logger.info("OPINION 현재가 보강 — 주가 미발견 code=%s", entity.stock_code)
            return {}
        return {
            "opinion_price": {
                "name": entity.name_ko,
                "stock_code": entity.stock_code,
                "close": price.close,
                "date": str(price.date),
            }
        }
