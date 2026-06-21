"""정본 config YAML 로더 — 파일 부재·파싱 실패를 진단 가능한 에러로 감싼다.

config/*.yaml은 코드와 함께 레포에 체크인되어 한 단위로 배포되는 정본이다. 파일이 없거나
깨졌다면 환경 문제가 아니라 배포 버그이므로(예: docker-compose의 ./config 마운트 누락) 조용히
빈 규칙으로 폴백하지 않고 즉시·명확하게 실패한다 — 빈 폴백은 비기사·보일러플레이트를 그대로
수집·임베딩하는 더 위험한 '조용한 품질 저하'를 부른다.

세 로더(rss_feeds·news_filter·body_processor)가 모듈 import 시점에 호출하므로, 맨
FileNotFoundError가 import 체인 깊은 곳에서 터지면 원인 파악이 느리다 → 파일명과 유력
원인을 담은 RuntimeError로 바꿔 던진다.
"""

from pathlib import Path
from typing import Any

import yaml


def read_config_yaml(path: Path) -> dict[str, Any]:
    """정본 config YAML을 읽어 dict로 반환한다(빈 파일은 빈 dict).

    파일 부재·파싱 실패 시 파일명과 유력 원인을 담은 RuntimeError로 감싸 던진다.
    """
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"정본 config '{path.name}' 없음({path}) — "
            "배포 시 ./config 마운트/파일 존재 여부를 확인하라."
        ) from exc
    except yaml.YAMLError as exc:
        raise RuntimeError(
            f"정본 config '{path.name}' 파싱 실패({path}) — YAML 문법을 확인하라."
        ) from exc
    return raw or {}
