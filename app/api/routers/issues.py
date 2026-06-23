from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, false, func, select, type_coerce
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.models import (
    BookmarkUpdateRequest,
    IssueActivityMutationResponse,
    IssueCardResponse,
    IssueDetailResponse,
    IssueListResponse,
    IssueReaderCardResponse,
    IssueTermResponse,
    QuizResponse,
    QuizSubmitRequest,
    QuizSubmitResponse,
    SourceArticleResponse,
)
from app.core.security import get_current_user, get_current_user_optional
from app.db.base import KST_NOW, get_db
from app.db.orm_models.company_entity import CompanyEntity
from app.db.orm_models.dictionary_term import DictionaryTerm
from app.db.orm_models.issue_docent import IssueDocent
from app.db.orm_models.news_analysis import NewsAnalysis
from app.db.orm_models.news_cluster import NewsCluster
from app.db.orm_models.user_issue_activity import UserIssueActivity
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

DOMESTIC_MARKET_EXCHANGES = {
    "KOSPI": ("KOSPI",),
    "KOSDAQ": ("KOSDAQ",),
}
OVERSEAS_MARKETS = {"NASDAQ", "SP500", "US_ETF", "GLOBAL"}


def _array_overlaps(column: Any, values: list[int]):
    return type_coerce(column, PG_ARRAY(Integer)).overlap(values)


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


def _terms(
    term_spans: list[dict[str, Any]], definitions: dict[str, str] | None = None
) -> list[IssueTermResponse]:
    seen: set[str] = set()
    terms: list[IssueTermResponse] = []
    definitions = definitions or {}
    for span in term_spans or []:
        name = str(span.get("term") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        terms.append(
            IssueTermResponse(name=name, definition=definitions.get(name, "준비 중인 용어입니다."))
        )
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
    docent: Any,
    cluster: Any | None,
    analysis: Any | None,
    articles: list[Any],
    term_definitions: dict[str, str] | None = None,
) -> IssueDetailResponse:
    base = build_issue_list_item(docent, cluster, analysis)
    return IssueDetailResponse(
        **base.model_dump(),
        cards=_cards(getattr(docent, "content_heads", []) or []),
        terms=_terms(getattr(docent, "term_spans", []) or [], term_definitions),
        sources=_sources(articles),
    )


def _quiz_response(issue_id: int, quizzes: list[dict[str, Any]]) -> QuizResponse:
    if len(quizzes or []) != 3:
        raise HTTPException(status_code=404, detail="Quiz not ready")
    return QuizResponse(
        issue_id=issue_id,
        quizzes=[
            {
                "quiz_id": str(quiz.get("quiz_id")),
                "kind": str(quiz.get("kind")),
                "question": str(quiz.get("question")),
                "options": list(quiz.get("options") or []),
            }
            for quiz in quizzes
        ],
    )


@router.get("", response_model=IssueListResponse)
async def list_issues(
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    q: str | None = None,
    sort: Literal["importance", "latest"] = "importance",
    market: str | None = None,
    sector_id: int | None = None,
    company_id: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> IssueListResponse:
    filters = []
    if q:
        filters.append(IssueDocent.title.ilike(f"%{q}%"))
    if sector_id is not None:
        filters.append(_array_overlaps(NewsAnalysis.sector_ids, [sector_id]))
    if company_id is not None:
        filters.append(_array_overlaps(NewsAnalysis.company_ids, [company_id]))
    if market:
        market_code = market.upper()
        if market_code in DOMESTIC_MARKET_EXCHANGES:
            company_ids = (
                await db.execute(
                    select(CompanyEntity.id).where(
                        CompanyEntity.market.in_(DOMESTIC_MARKET_EXCHANGES[market_code])
                    )
                )
            ).scalars().all()
            filters.append(
                _array_overlaps(NewsAnalysis.company_ids, list(company_ids))
                if company_ids
                else false()
            )
        elif market_code in OVERSEAS_MARKETS:
            filters.append(NewsAnalysis.origin == "해외")
        else:
            filters.append(false())

    order_by = (
        (IssueDocent.created_at.desc(),)
        if sort == "latest"
        else (NewsCluster.importance.desc(), IssueDocent.created_at.desc())
    )

    stmt = (
        select(IssueDocent, NewsCluster, NewsAnalysis)
        .join(NewsCluster, IssueDocent.cluster_id == NewsCluster.id)
        .outerjoin(NewsAnalysis, IssueDocent.cluster_id == NewsAnalysis.cluster_id)
        .where(*filters)
        .order_by(*order_by)
        .limit(limit)
        .offset(offset)
    )
    rows = (await db.execute(stmt)).all()
    total = await db.scalar(
        select(func.count(IssueDocent.id))
        .join(NewsCluster, IssueDocent.cluster_id == NewsCluster.id)
        .outerjoin(NewsAnalysis, IssueDocent.cluster_id == NewsAnalysis.cluster_id)
        .where(*filters)
    )
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
    term_names = [
        str(span.get("term") or "").strip()
        for span in (docent.term_spans or [])
        if str(span.get("term") or "").strip()
    ]
    dictionary_rows = (
        await db.execute(
            select(DictionaryTerm).where(DictionaryTerm.term.in_(set(term_names)))
        )
    ).scalars().all() if term_names else []
    definitions = {row.term: row.definition for row in dictionary_rows if row.status == "approved"}
    return build_issue_detail(docent, cluster, analysis, articles, definitions)


@router.get("/{issue_id}/quiz", response_model=QuizResponse)
async def get_issue_quiz(issue_id: int, db: AsyncSession = Depends(get_db)) -> QuizResponse:
    docent = await db.get(IssueDocent, issue_id)
    if docent is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return _quiz_response(issue_id, docent.quizzes or [])


@router.post("/{issue_id}/read", response_model=IssueActivityMutationResponse)
async def mark_issue_read(
    issue_id: int,
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IssueActivityMutationResponse:
    if await db.get(IssueDocent, issue_id) is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    values = {"read_at": KST_NOW, "updated_at": KST_NOW}
    await db.execute(
        pg_insert(UserIssueActivity)
        .values(user_id=user_id, issue_docent_id=issue_id, **values)
        .on_conflict_do_update(
            index_elements=["user_id", "issue_docent_id"],
            set_=values,
        )
    )
    await db.commit()
    return IssueActivityMutationResponse(issue_id=issue_id)


@router.put("/{issue_id}/bookmark", response_model=IssueActivityMutationResponse)
async def update_issue_bookmark(
    issue_id: int,
    payload: BookmarkUpdateRequest,
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IssueActivityMutationResponse:
    if await db.get(IssueDocent, issue_id) is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    values = {
        "bookmarked_at": KST_NOW if payload.bookmarked else None,
        "updated_at": KST_NOW,
    }
    await db.execute(
        pg_insert(UserIssueActivity)
        .values(user_id=user_id, issue_docent_id=issue_id, **values)
        .on_conflict_do_update(
            index_elements=["user_id", "issue_docent_id"],
            set_=values,
        )
    )
    await db.commit()
    return IssueActivityMutationResponse(issue_id=issue_id)


@router.get("/{issue_id}/quiz/result", response_model=QuizSubmitResponse)
async def get_issue_quiz_result(
    issue_id: int,
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> QuizSubmitResponse:
    activity = await db.scalar(
        select(UserIssueActivity).where(
            UserIssueActivity.user_id == user_id,
            UserIssueActivity.issue_docent_id == issue_id,
        )
    )
    if activity is None or activity.quiz_completed_at is None:
        raise HTTPException(status_code=404, detail="Quiz result not found")
    return QuizSubmitResponse(
        issue_id=issue_id,
        correct_count=activity.quiz_correct_count or 0,
        total_count=activity.quiz_total_count or 0,
        results=activity.quiz_results or [],
    )


@router.post("/{issue_id}/quiz/submit", response_model=QuizSubmitResponse)
async def submit_issue_quiz(
    issue_id: int,
    payload: QuizSubmitRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int | None = Depends(get_current_user_optional),
) -> QuizSubmitResponse:
    docent = await db.get(IssueDocent, issue_id)
    if docent is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    quizzes = docent.quizzes or []
    if len(quizzes) != 3:
        raise HTTPException(status_code=404, detail="Quiz not ready")

    results = []
    for quiz in quizzes:
        quiz_id = str(quiz.get("quiz_id"))
        answer_index = int(quiz.get("answer_index"))
        selected_index = payload.answers.get(quiz_id)
        is_correct = selected_index == answer_index
        results.append(
            {
                "quiz_id": quiz_id,
                "kind": str(quiz.get("kind")),
                "selected_index": selected_index,
                "answer_index": answer_index,
                "is_correct": is_correct,
                "explanation": str(quiz.get("explanation") or ""),
            }
        )
    correct_count = sum(1 for result in results if result["is_correct"])
    if user_id is not None:
        values = {
            "quiz_answers": payload.answers,
            "quiz_results": results,
            "quiz_correct_count": correct_count,
            "quiz_total_count": len(results),
            "quiz_completed_at": KST_NOW,
            "updated_at": KST_NOW,
        }
        await db.execute(
            pg_insert(UserIssueActivity)
            .values(user_id=user_id, issue_docent_id=issue_id, **values)
            .on_conflict_do_update(
                index_elements=["user_id", "issue_docent_id"],
                set_=values,
            )
        )
        await db.commit()
    return QuizSubmitResponse(
        issue_id=issue_id,
        correct_count=correct_count,
        total_count=len(results),
        results=results,
    )
