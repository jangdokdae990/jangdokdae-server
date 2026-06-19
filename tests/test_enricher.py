"""DataEnricher 단위 테스트 — OPINION 현재가 key 조회 (설계 08 §5, 10 §6).

DB 조회(get_company_by_name·get_latest_stock_price)는 monkeypatch로 가로챈다.
"""

import types
from datetime import date

import pytest

from services.analyzer import enricher as enricher_mod
from services.analyzer.enricher import DataEnricher
from services.analyzer.schemas import (
    Article,
    ClassificationResult,
    CompanyTag,
    Issue,
)


def _classification(frame: str, companies: list[CompanyTag]) -> ClassificationResult:
    return ClassificationResult(
        scope_reasoning="r",
        scope="회사",
        frame_reasoning="r",
        frame=frame,
        origin="국내",
        direction="하락",
        confidence=0.9,
        evidence="e",
        company_tags=companies,
    )


def _issue() -> Issue:
    return Issue(cluster_id=1, main_article=Article(title="t", body="b", url="u"))


@pytest.fixture
def patch_lookups(monkeypatch):
    state = {"entity": None, "price": None}

    async def fake_get_company(db, name):
        return state["entity"]

    async def fake_get_price(db, code):
        return state["price"]

    monkeypatch.setattr(enricher_mod, "get_company_by_name", fake_get_company)
    monkeypatch.setattr(enricher_mod, "get_latest_stock_price", fake_get_price)
    return state


async def test_opinion_returns_current_price(patch_lookups):
    patch_lookups["entity"] = types.SimpleNamespace(name_ko="에코프로", stock_code="086520")
    patch_lookups["price"] = types.SimpleNamespace(close=120000.0, date=date(2026, 6, 15))
    cls = _classification("OPINION", [CompanyTag(name="에코프로", role="primary")])

    result = await DataEnricher().enrich(object(), cls, _issue())

    assert result["opinion_price"]["name"] == "에코프로"
    assert result["opinion_price"]["stock_code"] == "086520"
    assert result["opinion_price"]["close"] == 120000.0
    assert result["opinion_price"]["date"] == "2026-06-15"


async def test_non_opinion_is_noop(patch_lookups):
    cls = _classification("EARNINGS", [CompanyTag(name="삼성전자", role="primary")])
    assert await DataEnricher().enrich(object(), cls, _issue()) == {}


async def test_opinion_entity_miss_returns_empty(patch_lookups):
    patch_lookups["entity"] = None  # 엔티티 미발견
    cls = _classification("OPINION", [CompanyTag(name="듣보종목", role="primary")])
    assert await DataEnricher().enrich(object(), cls, _issue()) == {}


async def test_opinion_price_miss_returns_empty(patch_lookups):
    patch_lookups["entity"] = types.SimpleNamespace(name_ko="에코프로", stock_code="086520")
    patch_lookups["price"] = None  # 주가 미발견
    cls = _classification("OPINION", [CompanyTag(name="에코프로", role="primary")])
    assert await DataEnricher().enrich(object(), cls, _issue()) == {}


async def test_opinion_no_company_returns_empty(patch_lookups):
    cls = _classification("OPINION", [])  # 기업 태그 없음
    assert await DataEnricher().enrich(object(), cls, _issue()) == {}
