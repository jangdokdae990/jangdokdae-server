"""수집 제외 필터 — 비기사성 뉴스(부고·인사·포토·AI 요약 카드 등)를 수집 단계에서 거른다.

제외 규칙의 정본은 코드 상수가 아니라 YAML(config/news_filter.yaml)이다 — 새 카테고리
추가를 코드 배포 없이 운영 중 처리하기 위함(news_feeds.yaml·news_body.yaml과 동일 원칙).

판정 방식:
- 제목 맨 앞 '태그'를 괄호 종류와 무관하게 추출([ ] ( ) < > 【 】 （ ））해, 안쪽 키워드가
  제외 키워드 집합에 정확히 있으면 비기사로 본다. 괄호 변형(<부고>·【부고】)까지 한 번에
  잡는다. 정상 기사 태그([단독]·[종합]·[속보] 등)는 집합에 없으니 그대로 통과한다.
  (정확 일치라 "[발표]"의 태그 '발표'가 키워드 '표'에 걸리는 오탐도 없다.)
- 제목/요약에 면책 문구(AI 자동요약 등)가 박혀 있으면 비기사로 본다.
"""

import re
from pathlib import Path

from utils.config_loader import read_config_yaml

# 필터 정본 — 루트 config/news_filter.yaml. 이 파일 기준 상대 경로로 찾는다.
FILTER_YAML = Path(__file__).resolve().parents[2] / "config" / "news_filter.yaml"

# 제목 맨 앞 괄호 태그 1개 추출 — 여는/닫는 괄호는 한·영·전각 변형을 모두 허용한다.
_CLOSE_CHARS = r"\]\)>】）"  # ] ) > 】 ）
_TAG_RE = re.compile(rf"^\s*[\[\(<【（]\s*([^{_CLOSE_CHARS}]{{1,12}}?)\s*[{_CLOSE_CHARS}]")


def _normalize(keyword: str) -> str:
    """비교용 정규화 — 공백 제거·소문자화로 'AI 카드뉴스' == 'ai카드뉴스' 매칭."""
    return re.sub(r"\s+", "", keyword).lower()


def load_filter(path: Path = FILTER_YAML) -> tuple[set[str], list[str]]:
    """YAML에서 (제목 키워드 집합, 본문 마커 리스트)를 로드한다(키워드는 정규화 후 저장)."""
    raw = read_config_yaml(path)
    keywords = {_normalize(k) for k in raw.get("excluded_title_keywords", [])}
    markers = list(raw.get("excluded_body_markers", []))
    return keywords, markers


# 모듈 임포트 시 1회 로드 (공개 API: rss_collector가 is_excluded를 임포트)
_TITLE_KEYWORDS, _BODY_MARKERS = load_filter()


def _leading_tag(title: str) -> str | None:
    """제목 맨 앞 괄호 태그의 안쪽 키워드를 정규화해 반환. 태그가 없으면 None."""
    match = _TAG_RE.match(title)
    return _normalize(match.group(1)) if match else None


def is_excluded(title: str, summary: str = "") -> bool:
    """비기사성 뉴스면 True — 기자 작성 기사가 아니므로 수집에서 제외한다."""
    tag = _leading_tag(title)
    if tag is not None and tag in _TITLE_KEYWORDS:
        return True
    haystack = f"{title}\n{summary}"
    return any(marker in haystack for marker in _BODY_MARKERS)
