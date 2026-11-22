"""촬영 화면 배치 — 가로: 미리보기 한가운데 + 오른쪽 세로 4칸, 세로: 미리보기 위 + 아래 한 줄 4칸."""

from __future__ import annotations

import pytest

import pygame

from walnut.booth_design import load
from walnut.stage import geometry
from walnut.scenes.capture import capture_layout, fit, thumb_window


def test_window_shows_all_when_four_or_less():
    assert thumb_window(range(4), 0) == [0, 1, 2, 3]
    assert thumb_window(range(2), 1) == [0, 1]
    assert thumb_window(range(1), 0) == [0]


def test_window_ends_at_current_cut_with_recent_shots_above():
    # 18장: 지금 찍을 칸이 맨 아래, 그 위로 최근에 찍은 3장
    assert thumb_window(range(18), 0) == [0, 1, 2, 3]
    assert thumb_window(range(18), 3) == [0, 1, 2, 3]
    assert thumb_window(range(18), 5) == [2, 3, 4, 5]
    assert thumb_window(range(18), 17) == [14, 15, 16, 17]
    assert thumb_window(range(18), 18) == [14, 15, 16, 17]  # 다 찍은 뒤


def test_window_in_retake_follows_the_cut_being_retaken():
    assert thumb_window(range(4), 2) == [0, 1, 2, 3]
    assert thumb_window(range(8), 6) == [3, 4, 5, 6]
    assert thumb_window(range(8), 1) == [0, 1, 2, 3]


RATIOS = [3 / 4, 2 / 3, 1.0, 4 / 3, 3 / 2, 16 / 9]


def landscape():
    return geometry(1920, 1080, load())


def portrait():
    return geometry(1080, 1920, load())


@pytest.mark.parametrize("ratio", RATIOS)
def test_landscape_preview_centered_large_and_thumbs_on_the_right(ratio):
    st = landscape()
    preview, cells = capture_layout(ratio, st)
    assert preview.center == (st.w // 2, st.h // 2)
    assert st.rect().contains(preview)
    assert preview.height >= 600 and (preview.height >= 950 or preview.width >= 1200)  # 최대한 크게
    assert abs(preview.width / preview.height - ratio) < 0.01
    assert len(cells) == 4
    for c in cells:
        assert c.left >= preview.right + 30  # 미리보기 테두리와 겹치지 않는다
        assert st.rect().contains(c)
        assert c.width >= 120 and c.height >= 120
    for a, b in zip(cells, cells[1:]):
        assert b.top > a.bottom  # 위에서 아래로, 겹치지 않게
    assert preview.left >= 300  # 왼쪽에 '컷 k / N' · 카운트다운 자리


@pytest.mark.parametrize("ratio", RATIOS)
def test_portrait_preview_on_top_and_thumbs_in_one_row_at_the_bottom(ratio):
    st = portrait()
    L = st.layout("capture")
    preview, cells = capture_layout(ratio, st)
    assert preview.centerx == st.w // 2
    assert preview.top == st.y(L["preview_top"])
    assert st.rect().contains(preview)
    assert abs(preview.width / preview.height - ratio) < 0.01
    assert len(cells) == L["thumb_row"]["slots"] == 4
    assert len({c.top for c in cells}) == 1 and len({c.height for c in cells}) == 1  # 한 줄
    for a, b in zip(cells, cells[1:]):
        assert b.left >= a.right + L["thumb_gap"] - 1  # 왼쪽에서 오른쪽으로, 겹치지 않게
    for c in cells:
        assert c.top >= preview.bottom + 8  # 미리보기 아래
        assert st.rect().contains(c)
    assert cells[-1].bottom == st.y(st.base_h - L["thumb_row_bottom"], "bottom")
    assert abs((cells[0].left + cells[-1].right) / 2 - st.w / 2) <= 1  # 가운데 줄


def test_portrait_layout_follows_a_taller_stage():
    st = geometry(900, 1600, load())  # 기준 크기 그대로
    tall = geometry(1000, 2200, load())  # 더 긴 세로 화면: 위는 위에, 줄은 아래에 붙는다
    p0, c0 = capture_layout(16 / 9, st)
    p1, c1 = capture_layout(16 / 9, tall)
    assert p1.top == p0.top
    assert c1[0].bottom - c0[0].bottom == tall.h - st.h


def test_fit_keeps_ratio_inside_box():
    assert fit(16 / 9, (1240, 1000)) == (1240, 698)
