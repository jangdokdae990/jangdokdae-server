"""issue_docent.quizzes 백필.

사용:
    uv run python scripts/backfill_quizzes.py --limit 10
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import select, update

from app.db.base import AsyncSessionLocal
from app.db.orm_models.issue_docent import IssueDocent
from app.db.orm_models.news_analysis import NewsAnalysis
from services.analyzer.quiz_generator import QuizGenerator
from services.analyzer.schemas import (
    Article,
    ClassificationResult,
    CompanyTag,
    ContentResult,
    Head,
    HookLines,
    Issue,
    TermSpan,
)

logger = logging.getLogger(__name__)


def _classification(row: NewsAnalysis) -> ClassificationResult:
    return ClassificationResult(
        scope_reasoning="backfill",
        scope=row.scope,
        frame_reasoning="backfill",
        frame=row.frame,
        origin=row.origin,
        direction=row.direction,
        confidence=row.confidence,
        evidence="backfill",
        sector_tags=row.sector_tags or [],
        company_tags=[CompanyTag(**tag) for tag in (row.company_tags or [])],
        term_tags=row.term_tags or [],
    )


def _content(row: IssueDocent) -> ContentResult:
    return ContentResult(
        heads=[Head(**head) for head in (row.content_heads or [])],
        hook_lines=HookLines(**row.hook_lines) if row.hook_lines else None,
        term_spans=[TermSpan(**span) for span in (row.term_spans or [])],
    )


async def _targets(db, issue_id: int | None, limit: int, force: bool):
    stmt = (
        select(IssueDocent, NewsAnalysis)
        .join(NewsAnalysis, IssueDocent.cluster_id == NewsAnalysis.cluster_id)
        .order_by(IssueDocent.id)
    )
    if issue_id is not None:
        stmt = stmt.where(IssueDocent.id == issue_id)
    if not force:
        stmt = stmt.where(IssueDocent.quizzes == [])
    if limit > 0:
        stmt = stmt.limit(limit)
    return (await db.execute(stmt)).all()


async def run(*, issue_id: int | None, limit: int, dry_run: bool, force: bool) -> None:
    generator = QuizGenerator()
    async with AsyncSessionLocal() as db:
        targets = await _targets(db, issue_id, limit, force)
    print(f"대상 issue_docent {len(targets)}건", flush=True)

    done = failed = skipped = 0
    for docent, analysis in targets:
        if dry_run:
            print(f"[dry-run] issue={docent.id} title={docent.title}", flush=True)
            skipped += 1
            continue
        try:
            issue = Issue(
                cluster_id=docent.cluster_id,
                main_article=Article(title=docent.title),
            )
            quizzes = generator.generate(issue, _classification(analysis), _content(docent))
            async with AsyncSessionLocal() as db:
                await db.execute(
                    update(IssueDocent)
                    .where(IssueDocent.id == docent.id)
                    .values(quizzes=[quiz.model_dump() for quiz in quizzes.quizzes])
                )
                await db.commit()
            done += 1
            print(f"[done] issue={docent.id}", flush=True)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            logger.exception("quiz backfill failed issue=%s", docent.id)
            print(f"[failed] issue={docent.id}: {exc}", flush=True)
    print(f"요약: done={done} skipped={skipped} failed={failed}", flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="issue_docent.quizzes 백필")
    parser.add_argument("--issue-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=10, help="대상 issue_docent 수. 0=무제한")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="기존 quizzes 덮어쓰기")
    args = parser.parse_args()
    asyncio.run(
        run(issue_id=args.issue_id, limit=args.limit, dry_run=args.dry_run, force=args.force)
    )
