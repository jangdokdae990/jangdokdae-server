import os
from datetime import datetime
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")

from app.api.routers.issues import build_issue_detail, build_issue_list_item


def test_build_issue_list_item_uses_docent_cluster_and_analysis():
    docent = SimpleNamespace(
        id=82,
        cluster_id=7,
        title="미국 기준금리 동결, 시장은 어떻게 반응할까?",
        hook_lines={"neutral": "연준의 동결 결정 이후 시장은 인하 시점을 보고 있습니다."},
        created_at=datetime(2026, 6, 22, 9, 30),
    )
    cluster = SimpleNamespace(size=3, importance=0.82)
    analysis = SimpleNamespace(
        frame="POLICY",
        scope="시장 전체",
        origin="해외",
        direction="중립",
        sector_tags=["시장·금리"],
        company_tags=[],
    )

    item = build_issue_list_item(docent, cluster, analysis)

    assert item.id == 82
    assert item.title == "미국 기준금리 동결, 시장은 어떻게 반응할까?"
    assert item.category == "시장·금리"
    assert item.teaser == "연준의 동결 결정 이후 시장은 인하 시점을 보고 있습니다."
    assert item.article_count == 3


def test_build_issue_detail_maps_content_heads_terms_and_sources():
    docent = SimpleNamespace(
        id=82,
        cluster_id=7,
        title="미국 기준금리 동결, 시장은 어떻게 반응할까?",
        hook_lines={},
        content_heads=[{"label": "무슨 일이에요", "answer": "연준이 기준금리를 동결했습니다."}],
        term_spans=[{"term": "기준금리", "sentence": "연준이 기준금리를 동결했습니다."}],
        created_at=datetime(2026, 6, 22, 9, 30),
    )
    cluster = SimpleNamespace(size=2, importance=0.82)
    analysis = SimpleNamespace(frame="POLICY", scope="시장 전체", sector_tags=[])
    articles = [
        SimpleNamespace(
            id=1,
            title="연준 기준금리 동결",
            url="https://example.com/fed",
            news_source="Reuters",
            published_at=datetime(2026, 6, 22, 8, 0),
        )
    ]

    detail = build_issue_detail(docent, cluster, analysis, articles)

    assert detail.cards[0].head == "무슨 일이에요"
    assert detail.cards[0].paragraphs == ["연준이 기준금리를 동결했습니다."]
    assert detail.terms[0].name == "기준금리"
    assert detail.terms[0].definition == "준비 중인 용어입니다."
    assert detail.sources[0].news_source == "Reuters"
