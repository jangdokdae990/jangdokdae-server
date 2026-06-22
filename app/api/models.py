from datetime import datetime

from pydantic import BaseModel


class IssueCardResponse(BaseModel):
    id: int
    title: str
    teaser: str
    category: str
    source: str
    article_count: int
    created_at: datetime


class IssueListResponse(BaseModel):
    items: list[IssueCardResponse]
    total: int
    limit: int
    offset: int


class IssueReaderCardResponse(BaseModel):
    head: str
    paragraphs: list[str]


class IssueTermResponse(BaseModel):
    name: str
    definition: str


class SourceArticleResponse(BaseModel):
    id: str
    title: str
    url: str
    news_source: str
    published_at: datetime | None


class IssueDetailResponse(IssueCardResponse):
    cards: list[IssueReaderCardResponse]
    terms: list[IssueTermResponse]
    sources: list[SourceArticleResponse]
