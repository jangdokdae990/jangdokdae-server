"""기업 데이터 전처리 — DART 사업보고서 XML을 3개 주요 섹션으로 추출·정제.

report_collector가 수집한 사업보고서 원문 XML을 사업의 내용/이사의 경영진단/감사의견
섹션으로 분할해 ReportChunk 청크를 만든다(뉴스 전처리와 분리된 기업 도메인 전처리).
외부 의존성 없이 stdlib(re, html)만 사용.
"""

import html
import re
from collections.abc import Callable

_NOISE_PATTERNS = [
    re.compile(r"^☞"),
    re.compile(r"^※\s*상세"),
    re.compile(r"\.jpg$|\.png$|\.jpeg$"),
    re.compile(r"^본문 위치로 이동$"),
]

_TITLE_PAT = re.compile(r"<TITLE[^>]*>(.*?)</TITLE>", re.IGNORECASE | re.DOTALL)
_ROMAN_PAT = re.compile(r"^\s*[IVXLCDM]+\.\s+.+$", re.IGNORECASE)
_SUB_PAT = re.compile(r"^\s*\d+\.\s+.+$")


def _split_by_titles(xml_text: str, pattern: re.Pattern[str]) -> list[tuple[str, str]]:
    """pattern에 맞는 TITLE 기준으로 XML을 (제목, 구간) 목록으로 분할."""
    candidates: list[tuple[str, int]] = []  # (title, start_pos)
    for m in _TITLE_PAT.finditer(xml_text):
        text = re.sub(r"\s+", " ", m.group(1)).strip()
        if pattern.match(text):
            candidates.append((text, m.start()))

    result: list[tuple[str, str]] = []
    for i, (title, start) in enumerate(candidates):
        end = candidates[i + 1][1] if i + 1 < len(candidates) else len(xml_text)
        result.append((title, xml_text[start:end]))
    return result


def _extract_major_sections(xml_text: str) -> dict[str, str]:
    """로마 숫자 대분류 TITLE 기준으로 XML을 섹션별로 분리."""
    return dict(_split_by_titles(xml_text, _ROMAN_PAT))


def _xml_to_lines(section_xml: str) -> list[str]:
    """XML 섹션을 정제된 줄 목록으로 변환."""
    block_close = r"</(P|TR|TBODY|TABLE|SECTION-\d+|TITLE)>"
    text = re.sub(block_close, "\n", section_xml, flags=re.IGNORECASE)
    text = re.sub(r"<(PGBRK|BR)\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[\t\r\f\v ]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r" {2,}", " ", text)
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def _drop_noise(lines: list[str]) -> list[str]:
    return [ln for ln in lines if not any(p.search(ln) for p in _NOISE_PATTERNS)]


def _base_lines(xml: str) -> list[str]:
    return _drop_noise(_xml_to_lines(xml))


def _preprocess_business(xml: str) -> str:
    lines = _base_lines(xml)
    return "\n".join(ln for ln in lines if not re.fullmatch(r"[\d\W_]+", ln) and len(ln) >= 2)


def _preprocess_director_analysis(xml: str) -> str:
    lines = _base_lines(xml)
    return "\n".join(re.sub(r"\s{2,}", " ", ln).strip() for ln in lines if len(ln) >= 2)


def _preprocess_audit_opinion(xml: str) -> str:
    lines = _base_lines(xml)
    keep_kw = re.compile(
        r"감사의견|회계법인|감사인|적정|한정|부적정|의견거절|내부회계|검토결론|감사기간|지정감사"
    )
    selected = [ln for ln in lines if keep_kw.search(ln)]
    return "\n".join(selected if len(selected) >= 20 else lines)


def _extract_subsections(section_xml: str) -> list[tuple[str, str]]:
    """아라비아 숫자 소제목(TITLE) 기준으로 분할. 없으면 [("", section_xml)]."""
    return _split_by_titles(section_xml, _SUB_PAT) or [("", section_xml)]


_PREPROCESSORS: dict[str, tuple[str, Callable[[str], str]]] = {
    "II. 사업의 내용":                  ("business_summary",  _preprocess_business),
    "IV. 이사의 경영진단 및 분석의견":   ("director_analysis", _preprocess_director_analysis),
    "V. 회계감사인의 감사의견 등":       ("audit_opinion",     _preprocess_audit_opinion),
}


def parse_report_sections(xml_text: str) -> dict[str, list[dict[str, str]]]:
    """사업보고서 XML에서 3개 섹션을 추출·정제.

    Returns:
        {"business_summary": [{"subsection": "1. ...", "content": "..."}, ...], ...}
    """
    raw_sections = _extract_major_sections(xml_text)
    result: dict[str, list[dict[str, str]]] = {}

    for title, (chunk_type, fn) in _PREPROCESSORS.items():
        xml = raw_sections.get(title, "")
        if not xml:
            result[chunk_type] = []
            continue
        chunks = []
        for subsection, sub_xml in _extract_subsections(xml):
            content = fn(sub_xml)
            if content.strip():
                chunks.append({"subsection": subsection, "content": content})
        result[chunk_type] = chunks

    return result
