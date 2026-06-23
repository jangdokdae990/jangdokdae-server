"""분류 체계 상수 + frame별 head 명세 로딩 (설계 08·10).

frame 내부 코드(영어, 불변)를 정본 키로 쓰고, 사용자 노출 한글 라벨·head 명세는
prompts/frame_head_specs.yaml에서 로드한다. 폐쇄형 섹터 목록·금지 표현은 분류·후처리·테스트가
참조하는 도메인 상수라 코드에 둔다(프롬프트 본문에도 같은 목록이 인라인으로 들어간다).
"""

from __future__ import annotations

from app.llm.prompt_loader import load_prompt

_FRAME_SPECS: dict[str, dict] = load_prompt("frame_head_specs")["frames"]

# 정본 frame 코드 (schemas.Frame Literal과 일치해야 한다).
FRAMES: list[str] = list(_FRAME_SPECS.keys())

# 폐쇄형 섹터 태그 = GICS 대분류 11개 (sectors.name_ko와 동일, 분류 프롬프트·테스트 단일 출처).
# LLM이 이 목록으로만 분류 → sector_tags가 곧 GICS 이름 → resolve_sector_ids가 sectors.id로 해소.
SECTOR_TAGS: list[str] = [
    "에너지", "소재", "산업재", "경기소비재", "필수소비재", "헬스케어",
    "금융", "IT", "커뮤니케이션서비스", "유틸리티", "부동산",
]

# 본문 금지 표현 (생성 후처리 필터·검증용).
FORBIDDEN_WORDS: list[str] = [
    "유망하다", "사야 한다", "주목할 만하다", "기회다", "수혜주",
    "확실하다", "분명하다", "급등 예상", "상승 기대",
]

# honest-blank(원문에 내용이 없어 "기사에 …없습니다"로 회피한) 답변을 식별하는 문구.
# head 다수가 이 문구를 담으면 발행 가치가 없어 needs_review로 격리한다(설계 15).
BLANK_PHRASES: list[str] = [
    "담고 있지 않", "제시되지 않았", "제시하고 있지 않", "포함하고 있지 않",
    "언급하고 있지 않", "나타나 있지 않", "되어 있지 않",
    "분석하기 어렵", "판단하기 어렵", "확인하기 어렵",
    "구체적인 정보가 없", "내용이 없", "찾아볼 수 없", "알 수 없",
]


def get_user_label(frame: str) -> str:
    """사용자에게 노출되는 frame 한글 이름 (예: EARNINGS → '실적이 나왔어요')."""
    return str(_FRAME_SPECS[frame]["user_label"])


def get_connection_hint(frame: str) -> str:
    """frame별 연결 모듈 구성 힌트."""
    return str(_FRAME_SPECS[frame]["connection_hint"])


def get_head_specs(frame: str, origin: str = "국내") -> list[dict]:
    """frame에 맞는 4개 head 명세. origin이 해외면 global_label로 head 라벨을 교체한다."""
    specs = []
    for s in _FRAME_SPECS[frame]["heads"]:
        label = s["global_label"] if (origin == "해외" and "global_label" in s) else s["label"]
        specs.append({**s, "label": label})
    return specs


def find_forbidden_words(text: str) -> list[str]:
    """본문에 등장한 금지 표현 목록 (중복 제거, 출현 순). 비면 통과."""
    found: list[str] = []
    for word in FORBIDDEN_WORDS:
        if word in text and word not in found:
            found.append(word)
    return found


def count_blank_heads(answers: list[str]) -> int:
    """honest-blank 문구를 포함한 head 답변 수 — 발행 무가치 판정용(설계 15)."""
    return sum(1 for a in answers if any(p in (a or "") for p in BLANK_PHRASES))
