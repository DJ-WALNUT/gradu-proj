"""shared/filter_fixtures.json — Python 필터가 공용 기대값과 같은 값을 내는지."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from walnut import filters

SHARED = Path(__file__).resolve().parents[2] / "shared"
FIX = json.loads((SHARED / "filter_fixtures.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("c", FIX["cases"], ids=lambda c: f"{c['filter']}-{c['in']}")
def test_apply_filter_matches_fixture(c):
    px = np.array([[c["in"]]], np.uint8)
    assert filters.apply_filter(px, c["filter"])[0, 0].tolist() == c["out"]


def test_generator_params_match_filters():
    spec = importlib.util.spec_from_file_location("gen_filter_fixtures", SHARED / "tools" / "gen_filter_fixtures.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.PARAMS == filters._PARAMS
    assert gen.FILTERS == filters.FILTERS
