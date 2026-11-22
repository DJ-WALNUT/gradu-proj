"""디자인 토큰의 가로 배치가 지금 Python 부스 상수와 같은지 확인한다."""

import sys
from pathlib import Path

import pygame

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "shared" / "booth-design"))
import booth_tokens  # noqa: E402

from walnut.scenes import capture, pick, print_copies, retake, review, share  # noqa: E402
from walnut.stage import geometry  # noqa: E402


def test_landscape_layout_matches_python_constants():
    t = booth_tokens.load()
    L = lambda s: booth_tokens.layout(t, s, "landscape")  # noqa: E731
    st = geometry(1920, 1080, t)
    preview, cells = capture.capture_layout(16 / 9, st)
    cap = L("capture")
    assert preview.size == capture.fit(16 / 9, tuple(cap["preview_box"]))
    assert preview.center == (960, 540)
    assert len(cells) == cap["thumb_slots"]
    right = preview.right + cap["thumb_inset"]
    tw = min(cap["thumb_max_w"], 1920 - right - 2 * cap["thumb_margin"])
    th = (preview.height - (cap["thumb_slots"] - 1) * cap["thumb_gap"]) // cap["thumb_slots"]
    assert all(c.size == (tw, th) for c in cells)
    assert cells[0].top == preview.top and cells[1].top - cells[0].bottom == cap["thumb_gap"]
    pk = L("pick")
    pl = pick.pick_layout(6, 3 / 4, st)
    grid = pygame.Rect(pk["grid"])
    assert pl.cols == pk["cols"] == 6 and pl.rows == 1
    assert all(grid.contains(c) for c in pl.cells)
    assert pl.cells[1].left - pl.cells[0].right == pk["gap"]
    assert pl.cells[0].top == grid.top and pl.cells[0].height == grid.height
    assert pl.done.size == tuple(pk["done_button"]) and pl.done.center == (960, pk["done_center_y"])
    rt = L("retake")
    rl = retake.retake_layout([3 / 4] * 4, st)
    assert rl.cols == rt["cols"] and rl.cuts[0].top == rt["rows_top"]
    assert all(c.w <= rt["thumb_box"][0] and c.h <= rt["thumb_box"][1] for c in rl.cuts)
    assert rl.cuts[1].left - rl.cuts[0].right == rt["col_gap"]
    assert rl.start.size == tuple(rt["button_sizes"][0]) and rl.start.centery == rt["buttons_y"]
    assert rl.cancel.centerx == rt["button_centers_x"][1]
    rv = L("review")
    vl = review.review_layout(st, 3 / 4, 2)
    assert vl.paper.center == tuple(rv["preview_center"]) and vl.paper.height <= rv["preview_box"][1]
    assert all(b.size == tuple(rv["button_size"]) and b.x == rv["buttons_x"] for b in vl.buttons)
    assert vl.buttons[0].top == rv["buttons_top"] and vl.buttons[1].top - vl.buttons[0].top == rv["button_step"]
    assert vl.auto_pos == (rv["buttons_x"] + rv["button_size"][0] // 2, rv["hint_y"])
    sh = L("share")
    assert sh["qr_size"] == 460 and tuple(sh["preview_box"]) == (620, 900)  # 토큰 자체(웹과 같이 쓰는 값)
    pc = L("print_copies")
    pl2 = print_copies.print_layout(st)
    assert pl2.center == tuple(pc["center"]) and pl2.r == pc["circle_r"]
    assert pl2.more.centerx - pl2.center[0] == pc["arrow_offset"] == pl2.center[0] - pl2.less.centerx
    assert pl2.confirm.size == tuple(pc["print_button"]) and pl2.confirm.centery == pc["print_button_y"]


def test_booth_copy_matches_shared():
    for name in ("tokens.json", "booth_tokens.py"):
        assert (ROOT / "booth/walnut/booth_design" / name).read_bytes() == (ROOT / "shared/booth-design" / name).read_bytes()
