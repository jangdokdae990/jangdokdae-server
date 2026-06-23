import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.api.routers.dictionary import create_candidates_from_issue, extract_terms
from services.analyzer.dictionary_generator import DictionaryDraft


def test_extract_terms_deduplicates_term_values_only():
    assert extract_terms(
        [
            {"term": "기준금리", "sentence": "첫 문장"},
            {"term": "기준금리", "sentence": "다른 문장"},
            {"term": "PER"},
            {"term": " "},
        ]
    ) == ["기준금리", "PER"]


@pytest.mark.asyncio
async def test_create_candidates_skips_existing_terms(monkeypatch):
    async def fake_generate(term: str):
        return DictionaryDraft(
            term_type="finance",
            definition=f"{term} 쉬운 설명",
            example=f"{term} 예시",
        )

    monkeypatch.setattr("app.api.routers.dictionary.generate_dictionary_draft", fake_generate)
    db = _FakeDB(existing_terms=["PER"])

    result = await create_candidates_from_issue(82, db)

    assert [item.term for item in result.created] == ["기준금리"]
    assert result.created[0].definition == "기준금리 쉬운 설명"
    assert result.skipped == ["PER"]
    assert db.committed is True


class _FakeDB:
    def __init__(self, existing_terms: list[str]):
        self.existing_terms = existing_terms
        self.committed = False

    async def get(self, _model, issue_id: int):
        return SimpleNamespace(
            id=issue_id,
            term_spans=[
                {"term": "PER", "sentence": "기존"},
                {"term": "기준금리", "sentence": "신규"},
                {"term": "기준금리", "sentence": "중복"},
            ],
        )

    async def execute(self, _stmt):
        if self.existing_terms is not None:
            terms = self.existing_terms
            self.existing_terms = None
            return _ExistingResult(terms)
        return _InsertResult(
            SimpleNamespace(
                id=1,
                term="기준금리",
                term_type="finance",
                definition="기준금리 쉬운 설명",
                example="기준금리 예시",
                source="llm",
                status="candidate",
            )
        )

    async def commit(self):
        self.committed = True


class _ExistingResult:
    def __init__(self, terms: list[str]):
        self.terms = terms

    def scalars(self):
        return self

    def all(self):
        return self.terms


class _InsertResult:
    def __init__(self, row):
        self.row = row

    def scalar_one_or_none(self):
        return self.row
