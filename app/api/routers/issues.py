from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.models import (
    IssueCardResponse,
    IssueDetailResponse,
    IssueListResponse,
    IssueReaderCardResponse,
    IssueTermResponse,
    SourceArticleResponse,
)
from app.db.base import get_db
from app.db.orm_models.issue_docent import IssueDocent
from app.db.orm_models.news_analysis import NewsAnalysis
from app.db.orm_models.news_cluster import NewsCluster
from app.db.queries import get_cluster_articles

router = APIRouter(prefix="/issues", tags=["issues"])

FRAME_CATEGORY = {
    "POLICY": "시장·금리",
    "PRICE": "시장",
    "TREND": "산업·기술",
    "EARNINGS": "실적",
    "INCIDENT": "이슈",
    "PLAN": "산업·정책",
    "OPINION": "전문가 의견",
}


def _category(analysis: Any | None) -> str:
    if analysis and getattr(analysis, "sector_tags", None):
        return str(analysis.sector_tags[0])
    if analysis and getattr(analysis, "frame", None):
        return FRAME_CATEGORY.get(str(analysis.frame), str(analysis.frame))
    return "시장"


def _teaser(docent: Any) -> str:
    hook_lines = getattr(docent, "hook_lines", None) or {}
    if hook_lines.get("neutral"):
        return str(hook_lines["neutral"])
    if hook_lines.get("pain"):
        return str(hook_lines["pain"])
    heads = getattr(docent, "content_heads", None) or []
    if heads and isinstance(heads[0], dict):
        return str(heads[0].get("answer") or "")[:120]
    return ""


def build_issue_list_item(
    docent: Any, cluster: Any | None, analysis: Any | None
) -> IssueCardResponse:
    return IssueCardResponse(
        id=docent.id,
        title=docent.title,
        teaser=_teaser(docent),
        category=_category(analysis),
        source="장독대 렌즈",
        article_count=getattr(cluster, "size", 0) or 0,
        created_at=docent.created_at,
    )


def _cards(content_heads: list[dict[str, Any]]) -> list[IssueReaderCardResponse]:
    cards: list[IssueReaderCardResponse] = []
    for head in content_heads or []:
        label = str(head.get("label") or head.get("head") or "핵심")
        answer = head.get("answer") or ""
        paragraphs = answer if isinstance(answer, list) else [str(answer)]
        cards.append(IssueReaderCardResponse(head=label, paragraphs=[p for p in paragraphs if p]))
    return cards


def _terms(term_spans: list[dict[str, Any]]) -> list[IssueTermResponse]:
    seen: set[str] = set()
    terms: list[IssueTermResponse] = []
    for span in term_spans or []:
        name = str(span.get("term") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        terms.append(IssueTermResponse(name=name, definition="준비 중인 용어입니다."))
    return terms


def _sources(articles: list[Any]) -> list[SourceArticleResponse]:
    return [
        SourceArticleResponse(
            id=str(article.id),
            title=article.title,
            url=article.url,
            news_source=article.news_source,
            published_at=article.published_at,
        )
        for article in articles
    ]


def build_issue_detail(
    docent: Any, cluster: Any | None, analysis: Any | None, articles: list[Any]
) -> IssueDetailResponse:
    base = build_issue_list_item(docent, cluster, analysis)
    return IssueDetailResponse(
        **base.model_dump(),
        cards=_cards(getattr(docent, "content_heads", []) or []),
        terms=_terms(getattr(docent, "term_spans", []) or []),
        sources=_sources(articles),
    )


@router.get("", response_model=IssueListResponse)
async def list_issues(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> IssueListResponse:
    filters = []
    if q:
        filters.append(IssueDocent.title.ilike(f"%{q}%"))

    stmt = (
        select(IssueDocent, NewsCluster, NewsAnalysis)
        .join(NewsCluster, IssueDocent.cluster_id == NewsCluster.id)
        .outerjoin(NewsAnalysis, IssueDocent.cluster_id == NewsAnalysis.cluster_id)
        .where(*filters)
        .order_by(NewsCluster.importance.desc(), IssueDocent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    total = await db.scalar(select(func.count()).select_from(IssueDocent).where(*filters))
    items = [build_issue_list_item(docent, cluster, analysis) for docent, cluster, analysis in rows]
    return IssueListResponse(
        items=items,
        total=total or 0,
        limit=limit,
        offset=offset,
    )


@router.get("/{issue_id}", response_model=IssueDetailResponse)
async def get_issue(issue_id: int, db: AsyncSession = Depends(get_db)) -> IssueDetailResponse:
    stmt = (
        select(IssueDocent, NewsCluster, NewsAnalysis)
        .join(NewsCluster, IssueDocent.cluster_id == NewsCluster.id)
        .outerjoin(NewsAnalysis, IssueDocent.cluster_id == NewsAnalysis.cluster_id)
        .where(IssueDocent.id == issue_id)
    )
    row = (await db.execute(stmt)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Issue not found")

    docent, cluster, analysis = row
    articles = await get_cluster_articles(db, cluster.member_news_ids)
    return build_issue_detail(docent, cluster, analysis, articles)
