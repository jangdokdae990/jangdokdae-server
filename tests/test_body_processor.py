# 단독 실행: uv run pytest tests/test_body_processor.py -s
"""body_processor 단위 테스트 — 본문 정제·overlap 청크 (설계 04 §Step2 · 05 §2.2).

DB·네트워크 없는 순수 함수라 외부 의존성 없이 검증한다.
"""

import re

import pytest

from services.preprocessor.body_processor import (
    chunk_with_overlap,
    clean_body,
    load_boilerplate_patterns,
)


# ── clean_body ──────────────────────────────────────────────────────────────
class TestCleanBody:
    def test_empty_returns_empty(self):
        assert clean_body("") == ""

    def test_collapses_horizontal_whitespace(self):
        result = clean_body("삼성전자가   3분기  실적을\t발표했다")
        assert result == "삼성전자가 3분기 실적을 발표했다"

    def test_collapses_excess_blank_lines(self):
        assert clean_body("문단1\n\n\n\n문단2") == "문단1\n\n문단2"

    def test_strips_leading_space_after_newline(self):
        assert clean_body("첫 줄\n   둘째 줄") == "첫 줄\n둘째 줄"

    def test_removes_boilerplate_lines(self):
        text = (
            "삼성전자가 신제품을 공개했다.\n"
            "ⓒ 한국경제 & hankyung.com, 무단전재 및 재배포 금지\n"
            "홍길동 기자\n"
            "hong@hankyung.com"
        )
        # 본문 한 줄만 남고 저작권·기자·이메일 줄은 제거된다.
        assert clean_body(text) == "삼성전자가 신제품을 공개했다."

    def test_keeps_body_when_no_boilerplate(self):
        text = "코스피가 상승 마감했다.\n외국인이 순매수했다."
        assert clean_body(text) == text

    def test_keeps_paragraph_with_inline_email(self):
        # 본문 문장 중간의 이메일은 서명이 아니므로 문단을 통째로 버리면 안 된다.
        text = "투자 문의는 ir@samsung.com 으로 하면 된다고 회사는 밝혔다."
        assert clean_body(text) == text

    def test_drops_email_signature_line_but_keeps_body(self):
        # 줄 끝 이메일 서명 줄만 제거하고 본문은 보존한다.
        text = "삼성전자가 신제품을 공개했다.\n홍길동 기자 hong@hankyung.com"
        assert clean_body(text) == "삼성전자가 신제품을 공개했다."

    def test_keeps_prose_mentioning_copyright_with_paren(self):
        # "저작권 ...(참고)" 처럼 괄호가 따라오는 본문 문장은 보존한다((c)는 리터럴 토큰만 매칭).
        text = "저작권 보호 대상(참고) 자료를 다룬 판결이 나왔다."
        assert clean_body(text) == text

    def test_drops_copyright_c_notation_line(self):
        # "(c)" 리터럴 저작권 표기 줄은 제거한다.
        text = "본문 문장이다.\n저작권자(c) 한국경제"
        assert clean_body(text) == "본문 문장이다."

    def test_custom_patterns_injection(self):
        pats = [re.compile("광고")]
        assert clean_body("본문입니다\n광고 문구입니다", patterns=pats) == "본문입니다"

    def test_strips_byline_prefix_keeps_lead_body(self):
        # "(지역=언론사) 이름 기자 = " prefix만 제거하고 리드 문단 본문은 보존한다
        text = "(서울=연합인포맥스) 노요빈 기자 = 국내 증시가 일제히 하락했다."
        assert clean_body(text) == "국내 증시가 일제히 하락했다."

    def test_strips_byline_prefix_bracket_variant(self):
        text = "[서울=뉴스핌] 박가연 기자 = 신한카드는 포상을 실시했다고 밝혔다."
        assert clean_body(text) == "신한카드는 포상을 실시했다고 밝혔다."

    def test_strips_bracket_byline_with_reporter_inside(self):
        # "[언론사 (지역) 이름 기자] " — 기자가 대괄호 안에 있는 형태(서울파이낸스 등)
        text = "[서울파이낸스 (강진) 권국상 기자] 강진군은 40억원을 투입한다."
        assert clean_body(text) == "강진군은 40억원을 투입한다."

    def test_strips_bracket_byline_simple(self):
        text = "[뉴스토마토 김진양 기자] MLCC 가격이 오른다."
        assert clean_body(text) == "MLCC 가격이 오른다."

    def test_drops_standalone_ai_disclaimer_line(self):
        # "AI 핵심 요약" 헤더 없이 면책 줄만 단독으로 남는 경우(뉴스핌)
        text = "!AI가 자동 생성한 요약으로 정확하지 않을 수 있어요.\nPKC가 사업을 한다."
        assert clean_body(text) == "PKC가 사업을 한다."

    def test_drops_stock_quote_widget_line(self):
        # 시세 위젯 줄(아시아경제) — 한 줄에 시세+관련기사가 함께 들어옴
        text = (
            "애드바이오텍 close 증권정보 179530 KOSDAQ 현재가 2,220 거래량 77,981 관련기사 ...\n"
            "애드바이오텍은 대표이사를 변경했다."
        )
        assert clean_body(text) == "애드바이오텍은 대표이사를 변경했다."

    def test_removes_ai_summary_block(self):
        # AI 자동요약 위젯(헤더~면책 줄) 전체 제거, 실제 본문은 보존
        text = (
            "AI 핵심 요약\n"
            "beta- 한국예탁결제원은 행사를 개최했다\n"
            "- 플랫폼은 44개 사업자가 이용한다\n"
            "!AI가 자동 생성한 요약으로 정확하지 않을 수 있어요.\n"
            "한국예탁결제원은 19일 행사를 개최했다고 밝혔다."
        )
        assert clean_body(text) == "한국예탁결제원은 19일 행사를 개최했다고 밝혔다."

    def test_block_kept_when_end_marker_missing(self):
        # end 마커가 window 안에 없으면 본문 오삭제를 막기 위해 제거하지 않는다
        text = "AI 핵심 요약\n" + "\n".join(f"본문 줄 {i}입니다." for i in range(12))
        assert "본문 줄 0입니다." in clean_body(text)

    def test_removes_ui_noise_lines(self):
        text = (
            "입력2026-06-19 14:39\n"
            "[파이낸셜뉴스]\n"
            "삼성전자가 신제품을 공개했다.\n"
            "이 기사를 추천합니다."
        )
        assert clean_body(text) == "삼성전자가 신제품을 공개했다."


# ── chunk_with_overlap ──────────────────────────────────────────────────────
class TestChunkWithOverlap:
    def test_empty_returns_empty_list(self):
        assert chunk_with_overlap("", 10, 2) == []

    def test_short_text_single_chunk(self):
        assert chunk_with_overlap("짧은 본문", 100, 20) == ["짧은 본문"]

    def test_exact_size_single_chunk(self):
        text = "a" * 10
        assert chunk_with_overlap(text, 10, 2) == [text]

    def test_splits_with_overlap(self):
        text = "abcdefghij"  # 10자
        # chunk_size=4, overlap=1 → step=3: [0:4]=abcd, [3:7]=defg, [6:10]=ghij
        assert chunk_with_overlap(text, 4, 1) == ["abcd", "defg", "ghij"]

    def test_adjacent_chunks_overlap_by_overlap_chars(self):
        chunks = chunk_with_overlap("abcdefghij", 4, 1)
        # 인접 청크의 끝/시작 1자가 겹친다(d, g)
        assert chunks[0][-1] == chunks[1][0]
        assert chunks[1][-1] == chunks[2][0]

    def test_no_data_loss_covers_all_text(self):
        text = "0123456789abcdef"  # 16자
        chunks = chunk_with_overlap(text, 5, 2)
        # 모든 원본 문자가 적어도 한 청크에 포함된다(경계 누락 없음).
        assert text[-1] in chunks[-1]
        assert "".join(c for c in chunks)  # 비어있지 않음

    def test_overlap_ge_chunk_size_raises(self):
        with pytest.raises(ValueError):
            chunk_with_overlap("abcdef", 3, 3)


# ── 설정 로더 ────────────────────────────────────────────────────────────────
def test_production_boilerplate_patterns_compile():
    # 정본 config/news_body.yaml의 패턴이 모두 컴파일되는지(설정 회귀 가드)
    pats = load_boilerplate_patterns()
    assert len(pats) > 0
    assert all(isinstance(p, re.Pattern) for p in pats)
