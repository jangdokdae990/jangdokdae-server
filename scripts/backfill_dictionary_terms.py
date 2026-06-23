"""issue_docent.term_spans 기반 dictionary_terms 백필.

사용:
    uv run python scripts/backfill_dictionary_terms.py --limit 10
    uv run python scripts/backfill_dictionary_terms.py --issue-id 82 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.routers.dictionary import extract_terms
from app.config import settings
from app.db.base import AsyncSessionLocal
from app.db.orm_models.dictionary_term import DictionaryTerm
from app.db.orm_models.issue_docent import IssueDocent
from services.analyzer.dictionary_generator import generate_dictionary_draft

logger = logging.getLogger(__name__)


async def _targets(db, issue_id: int | None, limit: int, force: bool) -> list[IssueDocent]:
    stmt = select(IssueDocent).where(IssueDocent.term_spans != [])
    if issue_id is not None:
        stmt = stmt.where(IssueDocent.id == issue_id)
    stmt = stmt.order_by(IssueDocent.id)
    if limit > 0:
        stmt = stmt.limit(limit)
    rows = list((await db.execute(stmt)).scalars().all())
    if force:
        return rows
    existing = set((await db.execute(select(DictionaryTerm.term))).scalars().all())
    return [
        row
        for row in rows
        if any(term not in existing for term in extract_terms(row.term_spans))
    ]


async def run(
    *,
    issue_id: int | None,
    limit: int,
    term_limit: int,
    dry_run: bool,
    force: bool,
) -> None:
    async with AsyncSessionLocal() as db:
        rows = await _targets(db, issue_id, limit, force)
    print(f"대상 issue_docent {len(rows)}건", flush=True)

    created = skipped = failed = 0
    for row in rows:
        async with AsyncSessionLocal() as db:
            terms = extract_terms(row.term_spans)
            existing = set(
                (
                    await db.execute(
                        select(DictionaryTerm.term).where(DictionaryTerm.term.in_(terms))
                    )
                )
                .scalars()
                .all()
            ) if terms and not force else set()
            for term in terms:
                if term_limit > 0 and created + skipped + failed >= term_limit:
                    print(
                        f"요약: created={created} skipped={skipped} failed={failed}",
                        flush=True,
                    )
                    return
                if term in existing:
                    skipped += 1
                    continue
                if dry_run:
                    print(f"[dry-run] issue={row.id} term={term}", flush=True)
                    skipped += 1
                    continue
                try:
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
                            first_issue_docent_id=row.id,
                        )
                        .on_conflict_do_nothing(index_elements=["term"])
                    )
                    await db.execute(stmt)
                    await db.commit()
                    created += 1
                    print(f"[created] {term}", flush=True)
                except Exception as exc:  # noqa: BLE001
                    await db.rollback()
                    failed += 1
                    logger.exception("dictionary backfill failed issue=%s term=%s", row.id, term)
                    print(f"[failed] issue={row.id} term={term}: {exc}", flush=True)
    print(f"요약: created={created} skipped={skipped} failed={failed}", flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="dictionary_terms 백필")
    parser.add_argument("--issue-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=10, help="대상 issue_docent 수. 0=무제한")
    parser.add_argument("--term-limit", type=int, default=0, help="처리할 용어 수. 0=무제한")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="기존 용어도 재생성 시도")
    args = parser.parse_args()
    asyncio.run(
        run(
            issue_id=args.issue_id,
            limit=args.limit,
            term_limit=args.term_limit,
            dry_run=args.dry_run,
            force=args.force,
        )
    )
