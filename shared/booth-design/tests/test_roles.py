"""색 역할 해석 · 대비 검사 테스트."""

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from booth_tokens import contrast, credit_visible, ink_on, load, resolve_roles  # noqa: E402
import booth_tokens  # noqa: E402
from cases import DEFAULT, HARD_CASES, random_cases  # noqa: E402

EVENT_KEYS = ("primary", "accent", "bg_top", "bg_bottom")


def ev_of(case: dict) -> dict:
    return {k: case[k] for k in EVENT_KEYS}


def test_default_event_keeps_primary_as_title():
    r = resolve_roles(load(), DEFAULT)
    assert r["title"] == "#1b2550" and r["line"] == "#1b2550" and r["action"] == "#e66e82"


def test_roles_cover_every_token_role():
    t = load()
    assert set(resolve_roles(t, DEFAULT)) == set(t["color"]["roles"])


def test_roles_check_both_backgrounds():
    ev = {**DEFAULT, "primary": "#595959", "bg_top": "#ffffff", "bg_bottom": "#5a5a5a"}
    r = resolve_roles(load(), ev)
    assert r["title"] != "#595959"  # 위쪽 흰 배경엔 7:1 로 읽혀도 아래쪽 회색 배경에서는 4.5 미만


def test_action_edge_when_accent_blends():
    ev = {**DEFAULT, "accent": "#fdf6f8"}
    assert resolve_roles(load(), ev)["action_edge"] == resolve_roles(load(), ev)["line"]
    # 기본 강조색 #e66e82 는 배경과 대비가 2.9/2.7 이라 3.0 미만 → 테두리가 붙는다 (보고서 참고)
    assert resolve_roles(load(), DEFAULT)["action_edge"] == resolve_roles(load(), DEFAULT)["line"]
    assert resolve_roles(load(), {**DEFAULT, "accent": "#c2185b"})["action_edge"] is None


def test_contrast_known_values():
    assert contrast("#000000", "#ffffff") == pytest.approx(21.0)
    assert contrast("#ffffff", "#ffffff") == pytest.approx(1.0)
    assert contrast("#123456", "#abcdef") == contrast("#abcdef", "#123456")


def test_ink_on_tie_prefers_dark():
    # 어두운 글씨 대비 >= 흰 글씨 대비이면 어두운 쪽이 이긴다
    assert ink_on(["#ffffff"]) == "#141821"
    assert ink_on(["#000000"]) == "#ffffff"


def test_ink_constants_match_tokens():
    fixed = load()["color"]["fixed"]
    assert booth_tokens.DARK_INK == fixed["dark_ink"] and booth_tokens.LIGHT_INK == fixed["light_ink"]


def test_mix_rounds_half_up():
    # floor(v + 0.5) — Python round() 는 은행원 반올림이라 .5 경계에서 JS 와 달라진다
    assert booth_tokens.mix("#000000", "#ffffff", 0.5) == "#808080"  # 127.5 → 128
    assert booth_tokens.mix("#040404", "#010101", 0.5) == "#030303"  # 2.5 → 3 (round() 는 2)


@pytest.mark.parametrize("case", HARD_CASES + random_cases(seed=20261019, n=60),
                         ids=lambda c: c["name"])
def test_text_roles_meet_aa(case):
    ev = ev_of(case)
    r = resolve_roles(load(), ev)
    bgs = [ev["bg_top"], ev["bg_bottom"]]
    best = max(min(contrast(i, b) for b in bgs) for i in ("#141821", "#ffffff"))
    for role in ("title", "hint"):
        got = min(contrast(r[role], b) for b in bgs)
        # 위아래 배경이 너무 달라 검정 · 흰색 어느 쪽도 4.5 를 못 넘는 행사면, 가능한 최선이어야 한다
        assert got >= 4.5 or (best < 4.5 and r[role] == ink_on(bgs)), role
    assert contrast(r["on_action"], ev["accent"]) >= 3.0  # README 의 on_action 3.0 근거 참고


def test_perforation_follows_primary_when_visible_on_paper():
    assert resolve_roles(load(), DEFAULT)["perforation"] == "#1b2550"


def test_perforation_uses_dark_ink_for_light_primary():
    ev = {**DEFAULT, "primary": "#f3e9d2"}
    assert resolve_roles(load(), ev)["perforation"] == "#141821"
    assert resolve_roles(load(), ev)["film"] == "#f3e9d2"  # film 은 그대로 primary


@pytest.mark.parametrize("case", HARD_CASES + random_cases(seed=20261019, n=60),
                         ids=lambda c: c["name"])
def test_perforation_visible_on_paper(case):
    r = resolve_roles(load(), ev_of(case))
    paper = load()["color"]["fixed"]["paper"]
    assert contrast(r["perforation"], paper) >= 3.0 or r["perforation"] == "#141821"


def test_expected_json_matches_python():
    data = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))
    assert data["version"] == 1 and data["cases"]
    for case in data["cases"]:
        assert resolve_roles(load(), case["event"]) == case["roles"], case["name"]


def test_credit_visible_default_true():
    assert credit_visible(None) is True and credit_visible({"branding": {}}) is True
