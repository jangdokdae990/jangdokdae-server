"""prompt_loader 단위 테스트 — prompts/*.yaml 로딩 (설계 10 §4)."""

import pytest

from app.llm.prompt_loader import load_prompt


def test_load_classify_prompt_has_system_and_user_template():
    data = load_prompt("news_classify")
    assert "system" in data
    assert "{main_title}" in data["user_template"]
    assert "{sub_headlines}" in data["user_template"]


def test_load_generate_prompt_has_head_block_placeholder():
    data = load_prompt("news_generate")
    assert "system" in data
    assert "{head_block}" in data["user_template"]
    assert "{main_article}" in data["user_template"]


def test_load_frame_head_specs_has_seven_frames():
    data = load_prompt("frame_head_specs")
    assert set(data["frames"]) == {
        "EARNINGS", "INCIDENT", "PLAN", "POLICY", "TREND", "OPINION", "PRICE",
    }


def test_load_missing_prompt_raises():
    with pytest.raises(FileNotFoundError):
        load_prompt("does_not_exist")
