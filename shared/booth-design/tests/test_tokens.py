"""디자인 토큰 로더 테스트."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import booth_tokens  # noqa: E402

SCREENS = ["pairing", "dial", "idle", "choose", "capture", "pick", "review", "retake", "share",
           "print_copies", "admin", "import_zip", "waiting", "photo_page"]


def test_load_has_all_groups():
    t = booth_tokens.load()
    assert set(t) >= {"version", "color", "type", "space", "layout", "print", "credit", "motion", "touch"}


def test_color_roles_only_point_to_event_inputs_or_fixed():
    t = booth_tokens.load()
    allowed = {"primary", "accent", "bg_top", "bg_bottom"} | set(t["color"]["fixed"])
    for role, src in t["color"]["roles"].items():
        assert src in allowed or src.startswith("computed:"), role


def test_validate_rejects_missing_group():
    t = booth_tokens.load()
    del t["motion"]
    with pytest.raises(ValueError, match="motion"):
        booth_tokens.validate(t)


def test_validate_rejects_bad_role_source():
    t = booth_tokens.load()
    t["color"]["roles"]["title"] = "hotpink"
    with pytest.raises(ValueError, match="title"):
        booth_tokens.validate(t)


def test_validate_rejects_unknown_computed_role():
    t = booth_tokens.load()
    t["color"]["roles"]["title"] = "computed:titel"
    with pytest.raises(ValueError, match="title"):
        booth_tokens.validate(t)


def test_validate_rejects_non_positive_number():
    t = booth_tokens.load()
    t["type"]["size"]["body"] = 0
    with pytest.raises(ValueError, match="body"):
        booth_tokens.validate(t)


def test_validate_rejects_missing_screen_orientation():
    t = booth_tokens.load()
    del t["layout"]["share"]["portrait"]
    with pytest.raises(ValueError, match="share"):
        booth_tokens.validate(t)


def test_every_screen_has_both_orientations():
    t = booth_tokens.load()
    for s in SCREENS:
        assert booth_tokens.layout(t, s, "landscape") and booth_tokens.layout(t, s, "portrait")


def test_layout_unknown_screen_raises_key_error():
    with pytest.raises(KeyError):
        booth_tokens.layout(booth_tokens.load(), "nope", "landscape")


@pytest.mark.parametrize("part", ["roles", "fixed", "alpha", "min_contrast"])
def test_validate_rejects_missing_color_part(part):
    t = booth_tokens.load()
    del t["color"][part]
    with pytest.raises(ValueError, match=f"color.{part}"):
        booth_tokens.validate(t)


@pytest.mark.parametrize("value", [0, -0.1, 1.5, "0.5", True])
def test_validate_rejects_alpha_out_of_range(value):
    t = booth_tokens.load()
    t["color"]["alpha"]["credit"] = value
    with pytest.raises(ValueError, match="color.alpha.credit"):
        booth_tokens.validate(t)


def test_validate_rejects_non_dict_layout_entry():
    t = booth_tokens.load()
    t["layout"]["share"] = [1, 2]
    with pytest.raises(ValueError, match="share"):
        booth_tokens.validate(t)


def test_validate_rejects_unknown_transition_duration():
    t = booth_tokens.load()
    t["motion"]["transition"]["slide"]["duration"] = "slow"
    with pytest.raises(ValueError, match="motion.transition.slide"):
        booth_tokens.validate(t)


def test_touch_long_press_ms():
    """관리자 숨은 동작(구석 길게 누르기) 시간 — 웹 부스 · 파이썬 부스가 같은 값을 읽는다."""
    t = booth_tokens.load()
    assert t["touch"]["long_press_ms"] == 1200


def test_breath_scale_must_grow():
    t = booth_tokens.load()
    t["motion"]["breath"]["scale"] = 1.0
    with pytest.raises(ValueError, match="motion.breath.scale"):
        booth_tokens.validate(t)


def test_breath_half_must_be_positive():
    t = booth_tokens.load()
    t["motion"]["breath"]["half_ms"] = 0
    with pytest.raises(ValueError, match="motion.breath.half_ms"):
        booth_tokens.validate(t)
