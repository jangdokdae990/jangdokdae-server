"""frames 단위 테스트 — frame별 head 명세·OPINION 신규·태그 상수 (설계 10 §2)."""

from services.analyzer import frames


def test_all_seven_frames_have_four_heads():
    assert set(frames.FRAMES) == {
        "EARNINGS", "INCIDENT", "PLAN", "POLICY", "TREND", "OPINION", "PRICE",
    }
    for frame in frames.FRAMES:
        specs = frames.get_head_specs(frame)
        assert len(specs) == 4, f"{frame} head 수가 4가 아님"
        for s in specs:
            assert s["label"]
            assert s["question"]


def test_each_frame_has_misconception_head3():
    # head3(★오해 방지)는 모든 frame에 존재해야 한다(설계 08 §3).
    for frame in frames.FRAMES:
        specs = frames.get_head_specs(frame)
        assert specs[2].get("misconception"), f"{frame} head3 오해 방지 누락"


def test_opinion_frame_heads_reflect_revised_design():
    # 09번 P0 + 08 §3-⑥ 갱신: 1단 종목·숫자 강제, 2단 괴리율, 3단 가정 가시화, 4단 검증 지표.
    specs = frames.get_head_specs("OPINION")
    assert frames.get_user_label("OPINION") == "전문가가 평가했어요"
    # 1단 — 종목·목표가·의견·직전대비 강제(작성 지침에 명시).
    assert "목표가" in specs[0]["guidance"] and "종목명" in specs[0]["guidance"]
    # 2단 — 괴리율.
    assert specs[1]["label"] == "지금 주가에서 얼마나 더 본 거예요?"
    assert "괴리율" in specs[1]["question"]
    assert "현재가 정보를 확인하지 못해" in specs[1]["guidance"]  # honest-blank 폴백
    # 3단 — 가정 가시화 + '목표가=미래 주가' 오해 방지.
    assert specs[2]["label"] == "이 숫자, 믿어도 될까요?"
    assert "가정" in specs[2]["question"]
    assert "목표가" in specs[2]["misconception"]


def test_global_origin_swaps_head_labels():
    # origin=해외면 global_label로 head1/2 라벨이 교체된다(INCIDENT 예).
    domestic = frames.get_head_specs("INCIDENT", "국내")
    overseas = frames.get_head_specs("INCIDENT", "해외")
    assert domestic[0]["label"] == "무슨 일이에요"
    assert overseas[0]["label"] == "해외에서 무슨 일이에요"


def test_find_forbidden_words():
    assert frames.find_forbidden_words("이 종목은 사야 한다, 정말 유망하다") == [
        "유망하다",
        "사야 한다",
    ]
    assert frames.find_forbidden_words("차분히 살펴볼 부분이 있습니다") == []


def test_sector_tags_closed_list():
    # 섹터 폐쇄목록 = GICS 대분류 11개 (sectors.name_ko와 일치).
    assert "IT" in frames.SECTOR_TAGS
    assert len(frames.SECTOR_TAGS) == 11
