"""분류·콘텐츠 생성 Pydantic 스키마 (LangChain with_structured_output 대상) 및 내부 데이터 구조.

호출 A(분류)·호출 B(생성)의 출력은 prompts/news_classify.yaml·news_generate.yaml의 JSON 스키마와
1:1로 대응한다. frame은 내부 코드(영어, 불변)를 정본 값으로 쓴다(설계 10 §2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# frame 내부 코드 — 사용자 노출 한글 라벨은 prompts/frame_head_specs.yaml의 user_label.
Frame = Literal["EARNINGS", "INCIDENT", "PLAN", "POLICY", "TREND", "OPINION", "PRICE"]
Scope = Literal["회사", "업종·테마", "시장 전체"]
Origin = Literal["국내", "해외"]
Direction = Literal["상승", "하락", "중립"]


# ════════════════════════════════════════════════════════
# 호출 A — 분류 결과
# ════════════════════════════════════════════════════════
class Alternative(BaseModel):
    scope: str = Field(default="", description="대안 scope(주인공)")
    frame: str = Field(default="", description="대안 frame(읽는 법 코드)")
    why: str = Field(default="", description="대안을 둔 이유")


class CompanyTag(BaseModel):
    name: str = Field(description="기업명")
    role: Literal["primary", "mentioned"] = Field(
        description="primary: 직접 영향 / mentioned: 단순 언급"
    )


class ClassificationResult(BaseModel):
    scope_reasoning: str = Field(description="본문 대부분이 누구 이야기인지 한 문장으로")
    scope: Scope
    frame_reasoning: str = Field(
        description="원인 사건이 독자에게 요구하는 판단이 무엇인지 한 문장으로"
    )
    frame: Frame
    origin: Origin
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    # 투자 관련성 게이트(설계 10 §2·평가 04). False면 후속 콘텐츠 생성을 건너뛴다(relevance 필터).
    # 기본 True — 하위호환(기존 분류 결과·LLM 미출력 시 관련 뉴스로 간주).
    is_investment_relevant: bool = Field(
        default=True,
        description=(
            "투자 판단과 관련된 뉴스면 True. 홍보·사회공헌·ESG·마케팅·교육·부고/인사 등 "
            "투자 판단과 무관한 비투자성 뉴스면 False."
        ),
    )
    evidence: str = Field(description="scope·frame 판단 근거가 된 본문 문장 1개")
    alternatives: list[Alternative] = Field(default_factory=list)
    sector_tags: list[str] = Field(default_factory=list)
    company_tags: list[CompanyTag] = Field(default_factory=list)
    term_tags: list[str] = Field(default_factory=list)


# ════════════════════════════════════════════════════════
# 호출 B — 본문 생성 결과
# ════════════════════════════════════════════════════════
class TermSpan(BaseModel):
    term: str = Field(description="term_tags에 해당하는 용어")
    sentence: str = Field(description="용어가 등장한 문장")


class ConnectionItem(BaseModel):
    sector: str = Field(description="영향받는 섹터")
    sentiment: Literal["긍정", "부정", "중립"]
    reason: str = Field(description="한 줄 이유")
    company_candidates: list[str] = Field(default_factory=list)


class EvidenceSpan(BaseModel):
    """(A) 단정형으로 쓴 핵심 사실과 그 근거가 된 기사 문장."""

    head: str = Field(description='근거가 달린 head ("head1"~"head4")')
    claim: str = Field(description="본문에서 단정한 핵심 사실")
    sentence: str = Field(description="그 근거가 된 기사 문장")


class HookLines(BaseModel):
    """본문 위에 얹는 첫 줄 2변형."""

    pain: str = Field(description="독자의 걱정·궁금증으로 말을 거는 질문형 한 줄")
    neutral: str = Field(description="무슨 일인지 담백하게 요약한 중립 한 줄 (질문 아님)")


class ContentDraft(BaseModel):
    """호출 B의 LLM 직접 출력. label·question은 코드가 채우므로 답변만 받는다."""

    title: str = Field(
        description=(
            "주린이가 한눈에 무슨 이슈인지 알 수 있는 제목 한 줄(30자 내외). "
            "종목 추천·방향 예측·금지 표현을 쓰지 않는다(본문 규칙과 동일)."
        )
    )
    answers: list[str] = Field(
        description="head1~head4 답변을 순서대로 정확히 4개. 각 답변은 2~4문장(head1은 1~2문장)."
    )
    hook_lines: HookLines = Field(description="pain·neutral 첫 줄 2가지.")
    evidence_spans: list[EvidenceSpan] = Field(
        default_factory=list,
        description="(A) 단정형으로 쓴 핵심 사실만. 추론형 문장은 적지 않는다.",
    )
    term_spans: list[TermSpan] = Field(default_factory=list)
    connection_module: list[ConnectionItem] = Field(default_factory=list)


class Head(BaseModel):
    """질문(question)과 그에 대한 답(answer) 쌍. label은 사용자 노출 제목."""

    label: str
    question: str
    answer: str


class ContentResult(BaseModel):
    """최종 콘텐츠. heads = [{label, question, answer}] × 4 + 첫 줄 2변형 + 부가 블록."""

    title: str = ""  # LLM 생성 이슈 제목. 누락 시 호출부가 원문 제목으로 폴백.
    heads: list[Head] = Field(default_factory=list)
    hook_lines: HookLines | None = None
    evidence_spans: list[EvidenceSpan] = Field(default_factory=list)
    term_spans: list[TermSpan] = Field(default_factory=list)
    connection_module: list[ConnectionItem] = Field(default_factory=list)


QuizKind = Literal["term", "issue", "domain"]


class QuizQuestion(BaseModel):
    quiz_id: str = Field(description='고정 id: "quiz-1"~"quiz-3"')
    kind: QuizKind
    question: str
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    explanation: str


class QuizOutput(BaseModel):
    quizzes: list[QuizQuestion] = Field(min_length=3, max_length=3)


# ════════════════════════════════════════════════════════
# 내부 데이터 구조
# ════════════════════════════════════════════════════════
class Article(BaseModel):
    title: str
    body: str = ""
    url: str = ""


class Issue(BaseModel):
    """하나의 이슈 = 메인 기사 1개 + 서브 기사 N개.

    클러스터의 대표(representative) 기사가 메인, 나머지(member)가 서브.
    cluster_id는 news_cluster.id (분석 결과 영속화 시 FK).
    """

    cluster_id: int
    main_article: Article
    sub_articles: list[Article] = Field(default_factory=list)
