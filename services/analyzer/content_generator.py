"""호출 B — 콘텐츠 생성기 (설계 10 §3).

분류 결과(frame)에 맞는 4-head 명세를 user 프롬프트에 주입해 본문·첫 줄·연결 모듈을 생성한다.
LLM은 answers 4개만 출력하고, label·question은 코드가 frame_head_specs에서 채워 결합한다.
프롬프트는 prompts/news_generate.yaml, 출력은 ContentDraft → ContentResult.
"""

from __future__ import annotations

import logging

from app.llm.chains import make_generator
from app.llm.prompt_loader import load_prompt
from services.analyzer import frames
from services.analyzer.schemas import (
    ClassificationResult,
    ContentDraft,
    ContentResult,
    Head,
    Issue,
    TermSpan,
)

logger = logging.getLogger(__name__)

_SUB_FACT_MAX_CHARS = 800


def _primary_company_name(classification: ClassificationResult) -> str | None:
    """primary 역할 기업명(없으면 첫 기업, 그것도 없으면 None) — OPINION 1단 가드용."""
    for tag in classification.company_tags:
        if tag.role == "primary":
            return tag.name
    return classification.company_tags[0].name if classification.company_tags else None


def _format_enrichment(enrichment: dict | None) -> str:
    """보강 컨텍스트를 user 프롬프트 [추가 자료] 블록으로 포맷. 없으면 빈 문자열."""
    if not enrichment:
        return ""
    price = enrichment.get("opinion_price")
    if price:
        return (
            "[추가 자료]\n"
            f"- {price['name']}({price['stock_code']}) 현재가: "
            f"{price['close']:,.0f}원 ({price['date']} 종가)"
        )
    return ""


def _dedup_term_spans(spans: list[TermSpan]) -> list[TermSpan]:
    """같은 용어(term)는 첫 등장만 남긴다 — OPINION 'MLCC 10회 중복' 대응(08 §3-⑥)."""
    seen: set[str] = set()
    deduped: list[TermSpan] = []
    for span in spans:
        if span.term in seen:
            continue
        seen.add(span.term)
        deduped.append(span)
    return deduped


def opinion_guard_ok(classification: ClassificationResult, content: ContentResult) -> bool:
    """OPINION 1단 종목 가드 — head1 답변에 primary 종목명이 박혔는지(08 §3-⑥).

    OPINION이 아니거나 분류에 기업명 자체가 없으면 가드 적용 불가 → 통과.
    """
    if classification.frame != "OPINION":
        return True
    name = _primary_company_name(classification)
    if not name:
        return True
    head1 = content.heads[0].answer if content.heads else ""
    return name in head1


def _build_head_block(specs: list[dict]) -> str:
    """head 명세 목록을 user 프롬프트용 텍스트 블록으로 조립한다."""
    lines: list[str] = []
    for i, s in enumerate(specs, start=1):
        lines.append(f'- head{i} "{s["label"]}"')
        lines.append(f"  질문: {s['question']}")
        if s.get("guidance"):
            lines.append(f"  작성 지침: {s['guidance']}")
        if s.get("misconception"):
            lines.append(f"  주린이 오해(반드시 짚어 막기): {s['misconception']}")
    return "\n".join(lines)


def _build_sub_facts(issue: Issue) -> str:
    if not issue.sub_articles:
        return "(없음)"
    facts: list[str] = []
    for a in issue.sub_articles:
        body = a.body[:_SUB_FACT_MAX_CHARS] if a.body else ""
        facts.append(f"- {a.title}" + (f": {body}" if body else ""))
    return "\n".join(facts)


def _assemble_heads(specs: list[dict], answers: list[str]) -> list[Head]:
    """frame head 명세(label·question)와 LLM answers를 순서대로 결합한다.

    answers가 4개가 아니면 짧은 쪽 길이에 맞춰 결합한다(부족분은 빈 답).
    """
    heads: list[Head] = []
    for i, s in enumerate(specs):
        answer = answers[i] if i < len(answers) else ""
        heads.append(Head(label=s["label"], question=s["question"], answer=answer))
    return heads


class ContentGenerator:
    """분류된 이슈 1건으로 콘텐츠를 생성한다. generator(LLM 체인)는 주입/지연 생성."""

    def __init__(self, generator=None) -> None:
        self._generator = generator

    @property
    def generator(self):  # noqa: ANN201
        if self._generator is None:
            self._generator = make_generator()
        return self._generator

    def _build_user_prompt(
        self,
        issue: Issue,
        classification: ClassificationResult,
        specs: list[dict],
        enrichment: dict | None,
    ) -> str:
        prompt = load_prompt("news_generate")
        main_article = (
            f"제목: {issue.main_article.title}\n본문: {issue.main_article.body}"
        )
        template: str = prompt["user_template"]
        return template.format(
            scope=classification.scope,
            frame_label=frames.get_user_label(classification.frame),
            origin=classification.origin,
            direction=classification.direction,
            head_block=_build_head_block(specs),
            connection_hint=frames.get_connection_hint(classification.frame),
            main_article=main_article,
            sub_facts=_build_sub_facts(issue),
            enrichment=_format_enrichment(enrichment),
        )

    def generate(
        self,
        issue: Issue,
        classification: ClassificationResult,
        enrichment: dict | None = None,
    ) -> ContentResult:
        """단일샷 생성. enrichment([추가 자료], 예: OPINION 현재가)를 프롬프트에 주입한다."""
        specs = frames.get_head_specs(classification.frame, classification.origin)
        user = self._build_user_prompt(issue, classification, specs, enrichment)
        system = load_prompt("news_generate")["system"]
        draft: ContentDraft = self.generator.invoke([("system", system), ("human", user)])

        # 금지 표현 후처리 — 발견 시 경고만 남기고 내용은 유지(스켈레톤).
        for i, answer in enumerate(draft.answers, start=1):
            hits = frames.find_forbidden_words(answer)
            if hits:
                logger.warning(
                    "cluster=%s head%d 금지 표현 검출: %s", issue.cluster_id, i, hits
                )

        return ContentResult(
            title=draft.title,
            heads=_assemble_heads(specs, draft.answers),
            hook_lines=draft.hook_lines,
            evidence_spans=draft.evidence_spans,
            term_spans=_dedup_term_spans(draft.term_spans),  # 같은 용어 반복 제거
            connection_module=draft.connection_module,
        )

    def generate_with_guard(
        self,
        issue: Issue,
        classification: ClassificationResult,
        enrichment: dict | None = None,
    ) -> tuple[ContentResult, bool]:
        """generate + OPINION 1단 종목 가드. 실패 시 1회 재생성, 그래도 실패면 (content, True).

        반환 두 번째 값 = needs_review 여부(가드 최종 실패).
        """
        content = self.generate(issue, classification, enrichment)
        if opinion_guard_ok(classification, content):
            return content, False
        logger.warning("OPINION 1단 종목명 누락 — 재생성 cluster=%s", issue.cluster_id)
        content = self.generate(issue, classification, enrichment)
        if opinion_guard_ok(classification, content):
            return content, False
        logger.warning("OPINION 1단 종목명 재생성 후에도 누락 cluster=%s", issue.cluster_id)
        return content, True
