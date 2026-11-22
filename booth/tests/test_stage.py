"""Stage — 모니터 크기에서 방향 · 논리 크기를 정한다 (웹 stageGeometry 와 같은 계산)."""

import json
from pathlib import Path

import pytest

from walnut import config
from walnut.booth_design import load
from walnut.stage import geometry

FIXTURES = Path(__file__).resolve().parents[2] / "shared" / "booth-design" / "stage_fixtures.json"


@pytest.mark.parametrize("c", json.loads(FIXTURES.read_text()))
def test_geometry_matches_web(c):
    s = geometry(*c["win"], load())
    assert (s.orientation, s.w, s.h) == (c["orientation"], *c["box"])


def test_pins_spread_the_extra_space():
    s = geometry(1600, 1200, load())  # 1920×1440, 남는 높이 360
    assert (s.y(100), s.y(100, "center"), s.y(100, "bottom")) == (100, 280, 460)


def test_x_pins_spread_the_extra_width():
    s = geometry(1200, 1600, load())  # 1440×1920, 남는 폭 360
    assert (s.x(100), s.x(100, "center"), s.x(100, "right")) == (100, 280, 460)


def test_portrait_type_scale():
    assert geometry(1080, 1920, load()).size("title") == 54
    assert geometry(1920, 1080, load()).size("title") == 72


def test_layout_follows_orientation():
    t = load()
    assert geometry(1920, 1080, t).layout("choose") == t["layout"]["choose"]["landscape"]
    assert geometry(1080, 1920, t).layout("choose") == t["layout"]["choose"]["portrait"]


def test_force_overrides_ratio():
    s = geometry(1920, 1080, load(), force="portrait")
    assert (s.orientation, s.w, s.h) == ("portrait", 1080, 1920)


def test_bad_orientation_value_is_auto():
    assert config.load({"BOOTH_ORIENTATION": "sideways"}).orientation == "auto"
    assert config.load({"BOOTH_ORIENTATION": "Portrait"}).orientation == "portrait"


def test_motion_defaults_on():
    assert config.load({}).motion is True
    assert config.load({"BOOTH_MOTION": "false"}).motion is False
