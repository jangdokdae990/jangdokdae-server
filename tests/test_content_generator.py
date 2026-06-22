"""content_generator 단위 테스트 — head 결합·프롬프트 조립·생성 (설계 10 §3).

LLM 호출은 가짜 체인(invoke가 ContentDraft를 반환)으로 대체한다.
"""

from services.analyzer import frames
from services.analyzer.content_generator import (
    ContentGenerator,
    _assemble_heads,
    _build_head_block,
    opinion_guard_ok,
)
from services.analyzer.schemas import (
    Article,
    ClassificationResult,
    CompanyTag,
    ContentDraft,
    ContentResult,
    Head,
    HookLines,
    Issue,
    TermSpan,
)


class _FakeChain:
    def __init__(self, result):
        self._result = result
        self.last_messages = None

    def invoke(self, messages):
        self.last_messages = messages
        return self._result


def _classification(frame: str = "EARNINGS") -> ClassificationResult:
    return ClassificationResult(
        scope_reasoning="한 기업 이야기",
        scope="회사",
        frame_reasoning="실적 발표가 원인",
        frame=frame,
        origin="국내",
        direction="상승",
        confidence=0.9,
        evidence="영업이익 9.2조",
        sector_tags=["IT"],
        company_tags=[CompanyTag(name="삼성전자", role="primary")],
        term_tags=["컨센서스"],
    )


def _issue() -> Issue:
    return Issue(
        cluster_id=1,
        main_article=Article(title="삼성전자 3분기 영업이익 9.2조", body="본문", url="u"),
        sub_articles=[Article(title="반도체 호조")],
    )


def _draft() -> ContentDraft:
    return ContentDraft(
        title="삼성전자 3분기 실적, 어떻게 읽을까",
        answers=["무슨 일", "예상 대비", "지속성", "앞으로"],
        hook_lines=HookLines(pain="안심해도 될까요", neutral="실적이 발표됐습니다"),
    )


def test_assemble_heads_pairs_specs_with_answers():
    specs = frames.get_head_specs("EARNINGS")
    heads = _assemble_heads(specs, ["a1", "a2", "a3", "a4"])
    assert len(heads) == 4
    assert heads[0].label == specs[0]["label"]
    assert heads[0].question == specs[0]["question"]
    assert [h.answer for h in heads] == ["a1", "a2", "a3", "a4"]


def test_assemble_heads_handles_short_answers():
    specs = frames.get_head_specs("EARNINGS")
    heads = _assemble_heads(specs, ["only-one"])
    assert len(heads) == 4
    assert heads[0].answer == "only-one"
    assert heads[3].answer == ""


def test_build_head_block_includes_labels_and_misconception():
    specs = frames.get_head_specs("EARNINGS")
    block = _build_head_block(specs)
    assert 'head1 "무슨 일이에요"' in block
    assert "주린이 오해(반드시 짚어 막기):" in block  # head3 misconception


def test_generate_returns_four_heads_and_hook():
    gen = ContentGenerator(generator=_FakeChain(_draft()))
    result = gen.generate(_issue(), _classification("EARNINGS"))
    assert len(result.heads) == 4
    # LLM이 생성한 제목이 결과로 전달되는지(원문 기사 제목과 무관).
    assert result.title == "삼성전자 3분기 실적, 어떻게 읽을까"
    assert result.hook_lines is not None
    assert result.hook_lines.pain == "안심해도 될까요"
    # frame 라벨이 user 프롬프트에 들어갔는지 확인.
    human_msg = gen.generator.last_messages[1][1]
    assert "실적이 나왔어요" in human_msg


def test_generate_for_opinion_uses_opinion_heads():
    gen = ContentGenerator(generator=_FakeChain(_draft()))
    result = gen.generate(_issue(), _classification("OPINION"))
    assert result.heads[0].label == "누가, 뭐라고 했어요?"
    assert result.heads[1].label == "지금 주가에서 얼마나 더 본 거예요?"
    assert result.heads[2].label == "이 숫자, 믿어도 될까요?"


def test_generate_injects_enrichment_current_price():
    gen = ContentGenerator(generator=_FakeChain(_draft()))
    enrichment = {
        "opinion_price": {
            "name": "에코프로",
            "stock_code": "086520",
            "close": 120000.0,
            "date": "2026-06-15",
        }
    }
    gen.generate(_issue(), _classification("OPINION"), enrichment)
    human_msg = gen.generator.last_messages[1][1]
    # 주입된 현재가 라인은 "...원 (날짜 종가)" 형태 — 유일 식별자.
    assert "120,000원" in human_msg
    assert "2026-06-15 종가)" in human_msg


def test_generate_no_enrichment_leaves_block_empty():
    # 보강 미주입 시 실제 현재가 라인("…종가)")은 없어야 한다.
    gen = ContentGenerator(generator=_FakeChain(_draft()))
    gen.generate(_issue(), _classification("OPINION"))
    assert "종가)" not in gen.generator.last_messages[1][1]


def test_term_spans_deduplicated():
    draft = ContentDraft(
        title="t",
        answers=["a1", "a2", "a3", "a4"],
        hook_lines=HookLines(pain="p", neutral="n"),
        term_spans=[
            TermSpan(term="MLCC", sentence="s1"),
            TermSpan(term="MLCC", sentence="s2"),
            TermSpan(term="컨센서스", sentence="s3"),
        ],
    )
    result = ContentGenerator(generator=_FakeChain(draft)).generate(
        _issue(), _classification("OPINION")
    )
    assert [t.term for t in result.term_spans] == ["MLCC", "컨센서스"]


def _opinion_classification() -> ClassificationResult:
    return _classification("OPINION")  # company_tags=[삼성전자 primary]


def _content_with_head1(answer: str) -> ContentResult:
    return ContentResult(
        heads=[Head(label="누가, 뭐라고 했어요?", question="q", answer=answer)]
        + [Head(label="l", question="q", answer="a") for _ in range(3)],
    )


def test_opinion_guard_ok_checks_company_in_head1():
    cls = _opinion_classification()
    assert opinion_guard_ok(cls, _content_with_head1("삼성전자 목표가 9만원 상향")) is True
    assert opinion_guard_ok(cls, _content_with_head1("AI 부품 시장이 변하고 있다")) is False
    # 비-OPINION은 항상 통과.
    assert opinion_guard_ok(_classification("EARNINGS"), _content_with_head1("업황")) is True


def test_generate_with_guard_passes_when_company_present():
    draft = ContentDraft(
        title="t",
        answers=["삼성전자 목표가 9만원으로 상향", "a2", "a3", "a4"],
        hook_lines=HookLines(pain="p", neutral="n"),
    )
    content, review = ContentGenerator(generator=_FakeChain(draft)).generate_with_guard(
        _issue(), _opinion_classification()
    )
    assert review is False
    assert "삼성전자" in content.heads[0].answer


def test_generate_with_guard_flags_review_after_retry():
    # 종목명 없는 draft를 계속 반환 → 1회 재생성 후에도 실패 → needs_review True.
    draft = ContentDraft(
        title="t",
        answers=["AI 부품 시장의 변화", "a2", "a3", "a4"],
        hook_lines=HookLines(pain="p", neutral="n"),
    )
    content, review = ContentGenerator(generator=_FakeChain(draft)).generate_with_guard(
        _issue(), _opinion_classification()
    )
    assert review is True


def test_count_blank_heads_counts_honest_blank_answers():
    answers = [
        "이 기사는 목표주가를 담고 있지 않습니다.",  # blank
        "삼성전자 영업이익이 9.2조로 늘었습니다.",      # 정상
        "구체적인 정보가 없습니다.",                    # blank
        "앞으로 반도체 가격을 보면 됩니다.",            # 정상
    ]
    assert frames.count_blank_heads(answers) == 2


def test_generate_with_guard_flags_review_on_blank_heads():
    # 원문에 내용이 없어 다수 head가 honest-blank → 재생성 없이 needs_review로 격리.
    draft = ContentDraft(
        title="t",
        answers=[
            "이 기사는 목표주가를 담고 있지 않습니다.",
            "현재 주가 대비 판단하기 어렵습니다.",
            "구체적인 정보가 없습니다.",
            "앞으로 볼 지표를 제시하고 있지 않습니다.",
        ],
        hook_lines=HookLines(pain="p", neutral="n"),
    )
    content, review = ContentGenerator(generator=_FakeChain(draft)).generate_with_guard(
        _issue(), _classification("EARNINGS")  # 비-OPINION이라 OPINION 가드는 통과
    )
    assert review is True


def test_generate_with_guard_passes_substantive_content():
    # 정상 콘텐츠(honest-blank 없음, 비-OPINION)는 발행 유지 — review False.
    content, review = ContentGenerator(generator=_FakeChain(_draft())).generate_with_guard(
        _issue(), _classification("EARNINGS")
    )
    assert review is False
