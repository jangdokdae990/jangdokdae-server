from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.models import DictionaryCandidateResponse, DictionaryTermResponse
from app.config import settings
from app.db.base import get_db
from app.db.orm_models.dictionary_term import DictionaryTerm
from app.db.orm_models.issue_docent import IssueDocent
from services.analyzer.dictionary_generator import generate_dictionary_draft

router = APIRouter(prefix="/dictionary", tags=["dictionary"])


def _response(row: DictionaryTerm) -> DictionaryTermResponse:
    return DictionaryTermResponse(
        id=row.id,
        term=row.term,
        term_type=row.term_type,
        definition=row.definition,
        example=row.example,
        source=row.source,
        status=row.status,
    )


def extract_terms(term_spans: list[dict]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for span in term_spans or []:
        term = str(span.get("term") or "").strip()
        if term and term not in seen:
            terms.append(term)
            seen.add(term)
    return terms


@router.get("", response_model=list[DictionaryTermResponse])
async def list_dictionary_terms(
    q: str | None = Query(default=None),
    type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> list[DictionaryTermResponse]:
    filters = []
    if q:
        filters.append(DictionaryTerm.term.ilike(f"%{q}%"))
    if type:
        filters.append(DictionaryTerm.term_type == type)
    if status:
        filters.append(DictionaryTerm.status == status)
    rows = (
        await db.execute(
            select(DictionaryTerm).where(*filters).order_by(DictionaryTerm.term).limit(100)
        )
    ).scalars().all()
    return [_response(row) for row in rows]


@router.get("/{term}", response_model=DictionaryTermResponse)
async def get_dictionary_term(
    term: str, db: AsyncSession = Depends(get_db)
) -> DictionaryTermResponse:
    row = await db.scalar(select(DictionaryTerm).where(DictionaryTerm.term == term))
    if row is None:
        raise HTTPException(status_code=404, detail="Dictionary term not found")
    return _response(row)


@router.post("/candidates/from-issue/{issue_id}", response_model=DictionaryCandidateResponse)
async def create_candidates_from_issue(
    issue_id: int,
    db: AsyncSession = Depends(get_db),
) -> DictionaryCandidateResponse:
    docent = await db.get(IssueDocent, issue_id)
    if docent is None:
        raise HTTPException(status_code=404, detail="Issue not found")

    terms = extract_terms(docent.term_spans)
    existing = set(
        (
            await db.execute(select(DictionaryTerm.term).where(DictionaryTerm.term.in_(terms)))
        ).scalars().all()
    ) if terms else set()

    created: list[DictionaryTerm] = []
    for term in terms:
        if term in existing:
            continue
        draft = await generate_dictionary_draft(term)
        stmt = (
            pg_insert(DictionaryTerm)
            .values(
                term=term,
                term_type=draft.term_type,
                definition=draft.definition,
                example=draft.example,
                source="llm",
                status="candidate",
                model_name=settings.dictionary_model,
                first_issue_docent_id=issue_id,
            )
            .on_conflict_do_nothing(index_elements=["term"])
            .returning(DictionaryTerm)
        )
        row = (await db.execute(stmt)).scalar_one_or_none()
        if row is not None:
            created.append(row)
    await db.commit()

    return DictionaryCandidateResponse(
        created=[_response(row) for row in created],
        skipped=[term for term in terms if term in existing],
    )
