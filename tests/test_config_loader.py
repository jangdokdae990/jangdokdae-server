# 단독 실행: uv run pytest tests/test_config_loader.py -s
"""config_loader 단위 테스트 — 정본 YAML 로드 실패를 진단 가능한 에러로 감싸는지 검증."""

from pathlib import Path

import pytest

from utils.config_loader import read_config_yaml


def test_reads_valid_yaml(tmp_path: Path):
    path = tmp_path / "x.yaml"
    path.write_text("a: 1\nb: [1, 2]\n", encoding="utf-8")
    assert read_config_yaml(path) == {"a": 1, "b": [1, 2]}


def test_empty_file_returns_empty_dict(tmp_path: Path):
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")
    assert read_config_yaml(path) == {}


def test_missing_file_raises_runtime_error_naming_file(tmp_path: Path):
    path = tmp_path / "absent.yaml"
    with pytest.raises(RuntimeError, match="absent.yaml"):
        read_config_yaml(path)


def test_malformed_yaml_raises_runtime_error(tmp_path: Path):
    path = tmp_path / "bad.yaml"
    path.write_text("a: [unterminated\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="파싱 실패"):
        read_config_yaml(path)
