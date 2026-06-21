"""본문 정제·청크 — 임베딩 입력용 순수 함수 (설계 04 §Step2 · 05 §2.2).

본문은 수집 시점이 아니라 **임베딩 직전(§5)에 trafilatura로 fetch**해 쓰고 폐기하므로,
수집 시점 모듈(news_preprocessor)과 분리한다. 이 모듈은 DB·네트워크 접근 없는 순수 함수다.

- `clean_body`: trafilatura가 추출한 평문에서 한국 언론 꼬리말(저작권·기자 서명 등)과
  잉여 공백을 제거한다(보일러플레이트 패턴은 config/news_body.yaml 정본).
- `chunk_with_overlap`: 인접 overlap을 둔 문자 기반 청크로 쪼갠다. 청크 크기·overlap은
  app/config.py(env)에 있고 bake-off로 교정한다(선정 모델 토큰 한계 종속).
"""

import re
from pathlib import Path

from utils.config_loader import read_config_yaml

# 보일러플레이트 패턴 정본 — 루트 config/news_body.yaml. 이 파일 기준 상대 경로.
NEWS_BODY_YAML = Path(__file__).resolve().parents[2] / "config" / "news_body.yaml"

# 공백 정규화 — 가로 공백 축약, 줄 앞 공백 제거, 빈 줄 축약.
_HSPACE = re.compile(r"[ \t\r\f\v]+")
_LINE_LEADING_SPACE = re.compile(r"\n[ \t]+")
_BLANK_LINES = re.compile(r"\n{3,}")


def load_boilerplate_patterns(path: Path = NEWS_BODY_YAML) -> list[re.Pattern[str]]:
    """config에서 보일러플레이트 줄 제거 정규식을 로드·컴파일한다(대소문자 무시).

    설정 파일·키가 없으면 빈 리스트(정제 안 함) — 잘못된 패턴은 re.error로 즉시 실패한다.
    """
    raw = read_config_yaml(path)
    return [re.compile(p, re.IGNORECASE) for p in raw.get("boilerplate_patterns", [])]


def load_byline_patterns(path: Path = NEWS_BODY_YAML) -> list[re.Pattern[str]]:
    """config에서 바이라인 prefix 치환 정규식을 로드·컴파일한다(대소문자 무시·MULTILINE).

    바이라인은 리드 문단 앞에 붙으므로(예: "(서울=연합) 홍길동 기자 = 본문...") 줄을 통째로
    지우면 본문이 날아간다 → 매치 부분만 치환 제거한다. `^`는 각 줄 시작에 맞춘다(MULTILINE).
    """
    raw = read_config_yaml(path)
    return [
        re.compile(p, re.IGNORECASE | re.MULTILINE)
        for p in raw.get("byline_patterns", [])
    ]


def load_boilerplate_blocks(
    path: Path = NEWS_BODY_YAML,
) -> list[tuple[re.Pattern[str], re.Pattern[str], int]]:
    """config에서 블록 제거용 (start, end, max_lines) 규칙을 로드·컴파일한다(대소문자 무시).

    AI 자동요약 위젯처럼 줄 단위로 못 지우는 영역을 start~end 마커로 통째 제거하기 위함.
    """
    raw = read_config_yaml(path)
    blocks: list[tuple[re.Pattern[str], re.Pattern[str], int]] = []
    for b in raw.get("boilerplate_blocks", []):
        # start·end가 모두 있어야 블록 규칙이 성립한다 — 하나라도 빠지면 건너뛴다
        # (config 오타로 import가 통째로 죽지 않게: "키 없으면 정제 안 함" 원칙).
        if "start" not in b or "end" not in b:
            continue
        blocks.append((
            re.compile(b["start"], re.IGNORECASE),
            re.compile(b["end"], re.IGNORECASE),
            int(b.get("max_lines", 10)),
        ))
    return blocks


def _drop_blocks(
    lines: list[str], blocks: list[tuple[re.Pattern[str], re.Pattern[str], int]]
) -> list[str]:
    """start 마커 줄부터 end 마커 줄까지(둘 다 포함) 제거한다.

    end를 start로부터 max_lines 안에서 못 찾으면 제거하지 않는다 — end가 없는 경우 본문
    전체가 통째로 날아가는 사고를 막는 안전장치다.
    """
    if not blocks:
        return lines
    drop = [False] * len(lines)
    i = 0
    while i < len(lines):
        rule = next((b for b in blocks if b[0].search(lines[i])), None)
        if rule is not None:
            _start, end_pat, max_lines = rule
            end_idx = next(
                (j for j in range(i, min(len(lines), i + max_lines))
                 if end_pat.search(lines[j])),
                None,
            )
            if end_idx is not None:
                for k in range(i, end_idx + 1):
                    drop[k] = True
                i = end_idx + 1
                continue
        i += 1
    return [ln for k, ln in enumerate(lines) if not drop[k]]


# 모듈 임포트 시 1회 컴파일 — 정제는 본문마다 호출되므로 매번 컴파일하지 않는다.
_BOILERPLATE: list[re.Pattern[str]] = load_boilerplate_patterns()
_BYLINE: list[re.Pattern[str]] = load_byline_patterns()
_BLOCKS: list[tuple[re.Pattern[str], re.Pattern[str], int]] = load_boilerplate_blocks()


def clean_body(
    text: str,
    *,
    patterns: list[re.Pattern[str]] | None = None,
    byline_patterns: list[re.Pattern[str]] | None = None,
) -> str:
    """본문 평문을 임베딩 입력용으로 정제한다.

    ① 공백 정규화 → ② 바이라인 prefix 치환 제거(리드 문단 본문은 보존) → ③ 블록 제거(AI
    자동요약 위젯 등) → ④ 보일러플레이트 줄 제거. patterns/byline_patterns를 주지 않으면
    config 정본을 쓴다(테스트 주입용 seam). 빈 입력은 빈 문자열.
    """
    if not text:
        return ""
    pats = _BOILERPLATE if patterns is None else patterns
    bylines = _BYLINE if byline_patterns is None else byline_patterns
    # ① 공백 정규화 — 가로 공백·줄 앞 공백·과도한 빈 줄을 정리.
    text = _HSPACE.sub(" ", text)
    text = _LINE_LEADING_SPACE.sub("\n", text)
    text = _BLANK_LINES.sub("\n\n", text)
    # ② 바이라인 prefix 제거 — 매치 부분만 치환(본문은 보존).
    for bp in bylines:
        text = bp.sub("", text)
    # ③ 블록 제거(start~end) → ④ 보일러플레이트 줄 제거(한 줄이라도 걸리면 버림).
    lines = _drop_blocks(text.split("\n"), _BLOCKS)
    kept = [line for line in lines if not any(p.search(line) for p in pats)]
    return "\n".join(kept).strip()


def chunk_with_overlap(text: str, chunk_size: int, overlap: int) -> list[str]:
    """본문을 인접 overlap을 둔 문자 기반 청크 리스트로 쪼갠다.

    각 청크는 chunk_size 문자, 인접 청크는 overlap 문자만큼 겹쳐 경계 문맥을 보존한다.
    빈 입력은 빈 리스트, chunk_size 이하 입력은 단일 청크. overlap은 chunk_size 미만이어야
    한다(이상이면 전진하지 못해 무한 루프 → ValueError).
    """
    if overlap >= chunk_size:
        raise ValueError(f"overlap({overlap})은 chunk_size({chunk_size})보다 작아야 한다")
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    step = chunk_size - overlap
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + chunk_size])
        if start + chunk_size >= len(text):
            break
        start += step
    return chunks
