"""필터 LUT 값 검사."""

from __future__ import annotations

import numpy as np

from walnut.filters import FILTERS, apply_filter


def test_filter_values():
    px = np.array([[[100, 150, 200]]], np.uint8)
    assert apply_filter(px, "original").tolist() == [[[100, 150, 200]]]
    assert apply_filter(px, "mono").tolist() == [[[141, 141, 141]]]
    assert apply_filter(px, "bright").tolist() == [[[124, 180, 236]]]
    assert apply_filter(px, "warm").tolist() == [[[118, 154, 186]]]
    assert apply_filter(np.array([[[250, 5, 0]]], np.uint8), "cool").tolist() == [[[236, 7, 18]]]
    assert apply_filter(px, "vintage").tolist() == [[[123, 156, 182]]]
    assert apply_filter(px, "nope").tolist() == [[[100, 150, 200]]]


def test_vintage_half_rounds_up():
    # 0.85*150+28 = 155.5 → 156 (float32 였다면 틀어질 수 있는 경계)
    out = apply_filter(np.array([[[150, 150, 150]]], np.uint8), "vintage")
    assert out[0, 0, 1] == 156


def test_clamped_and_new_array():
    px = np.array([[[0, 255, 255]]], np.uint8)
    out = apply_filter(px, "warm")
    assert out.tolist() == [[[18, 255, 241]]]
    same = apply_filter(px, "original")
    assert same is not px and same.dtype == np.uint8
    same[0, 0, 0] = 9
    assert px[0, 0, 0] == 0
    assert apply_filter(px, "cool").tolist()[0][0][0] == 0


def test_filter_names():
    assert FILTERS == ("original", "mono", "bright", "warm", "cool", "vintage")
