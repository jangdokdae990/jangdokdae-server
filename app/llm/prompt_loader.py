"""prompts/*.yaml 로더.

CLAUDE.md 원칙: LLM 프롬프트는 코드가 아닌 prompts/*.yaml에서 관리한다.
여기서 한 곳으로 모아 로드하고, 같은 프롬프트의 반복 파싱을 lru_cache로 막는다.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

# app/llm/prompt_loader.py → parents[2] = 레포 루트 → prompts/
_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"


@functools.lru_cache(maxsize=None)
def load_prompt(name: str) -> dict[str, Any]:
    """prompts/<name>.yaml을 파싱해 dict로 반환한다 (확장자 제외한 이름)."""
    path = _PROMPTS_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"프롬프트 파일이 없습니다: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"프롬프트 YAML 형식이 dict가 아닙니다: {path}")
    return data
