"""장면별 터치 동작 — 장면을 새 디자인으로 바꾸면서 하나씩 더한다."""

from __future__ import annotations

import json

import pygame
import pytest

from walnut.scenes.choose import ChooseScene
from walnut.scenes.idle import IdleScene
from walnut.scenes.waiting import WaitingScene
from tests.test_app import _save_device, paired_with_bundle, step  # noqa: F401
from tests.test_touch_app import FakeClock, down, tap, up


@pytest.fixture
def app(make_app, paired_with_bundle):
    a = make_app()
    a.time_fn = clock = FakeClock()
    a.fake_clock = clock
    a._went_at = clock.t - 10
    step(a)
    return a


def test_idle_tap_on_button_starts(app):
    assert isinstance(app.scene, IdleScene)
    app.fake_clock.t += 1
    tap(app, app.scene.start_rect().center)
    assert isinstance(app.scene, ChooseScene)


@pytest.mark.parametrize("pos", [(960, 900), (960, 300), (100, 760)])
def test_idle_tap_outside_button_does_nothing(app, pos):
    app.fake_clock.t += 1
    assert not app.scene.start_rect().collidepoint(pos)
    tap(app, pos)
    assert isinstance(app.scene, IdleScene)


def test_idle_start_ignored_during_guard(app):
    btn = app.scene.start_rect().center
    step(app, down(btn), up(btn))
    app.fake_clock.t += 1
    app.go(IdleScene(app))
    step(app)
    app.fake_clock.t += 0.1
    tap(app, btn)
    assert isinstance(app.scene, IdleScene)


def test_waiting_tap_does_nothing(make_app, tmp_path, fake_server):
    _save_device(tmp_path, fake_server.url)
    a = make_app()
    a.time_fn = clock = FakeClock()
    clock.t += 10
    step(a)
    assert isinstance(a.scene, WaitingScene)
    clock.t += 1
    tap(a, (960, 540))
    assert isinstance(a.scene, WaitingScene)


# ---- 고르기 ----
from walnut.scenes.choose import CHOOSE_IDLE_SEC  # noqa: E402
from walnut.touch import Gesture  # noqa: E402
from tests.test_app import key  # noqa: E402


@pytest.fixture
def choose(app):
    """항목 5개짜리 필터 고르기 (장면 전환 직후 탭 버리기 시간은 지난 상태)."""
    sc = ChooseScene(app, "F", [(f, f) for f in ("a", "b", "c", "d", "e")])
    app.go(sc)
    step(app)
    app.fake_clock.t += 1
    return sc


def adv(app, sec):
    """sec 초 동안 흘려보낸다 (한 프레임에 크게 — 입력 없이 시계만)."""
    app.fake_clock.t += sec
    app.step(sec, [])


def _row(app, i):
    """i 번째 항목이 화면에서 차지하는 줄의 가운데 (pos 가 sel 에 닿은 뒤)."""
    L = app.stage.layout("choose")
    sc = app.scene
    top = app.stage.y(L["list_top"])
    bottom = top + L["list_row_h"] * L["list_visible"]
    y = round(top + (i - sc._first(L["list_visible"]) + 0.5) * L["list_row_h"])
    return (app.stage.x(L["list_x"]) + L["list_item_w"] // 2, min(max(y, top + 5), bottom - 5))  # 창 끝에 반쯤 걸린 항목은 보이는 쪽을 누른다


def test_tap_other_item_moves_then_tap_again_chooses(app, choose):
    tap(app, _row(app, 2))
    assert choose.sel == 2 and app.scene is choose
    assert app._chosen.get("F") != "c"  # 처음 누른 것은 옮기기만 한다
    adv(app, 1.0)  # 목록이 미끄러져 도착
    tap(app, _row(app, 2))
    assert app._chosen["F"] == "c" and app.scene is not choose  # 고른 항목을 다시 눌러야 결정


def test_tap_then_remote_continues_from_same_item(app, choose):
    tap(app, _row(app, 3))
    assert choose.remote_state() == "L|F|3|5|d"
    step(app, key(pygame.K_LEFT))
    assert choose.sel == 2 and choose.remote_state() == "L|F|2|5|c"


def test_remote_then_tap_selected_chooses(app, choose):
    step(app, key(pygame.K_RIGHT), key(pygame.K_RIGHT))
    adv(app, 1.0)
    tap(app, _row(app, 2))
    assert app.scene is not choose


def test_drag_settles_on_nearest_item(app, choose):
    L = app.stage.layout("choose")
    rh = L["list_row_h"]
    choose.drag(Gesture("drag", (0, 0), (0, 0), 0, -int(rh * 2.4)))  # 위로 2.4칸
    assert abs(choose.pos - 2.4) < 1e-6
    choose.drag(Gesture("drag_end", (0, 0), (0, 0), 0, -int(rh * 2.4), 0.0, 0.0))
    assert choose.sel == 2
    # 끝을 넘기면 돌지 않고 멈춘다
    choose.drag(Gesture("drag", (0, 0), (0, 0), 0, -rh * 9))
    choose.drag(Gesture("drag_end", (0, 0), (0, 0), 0, -rh * 9, 0.0, 0.0))
    assert choose.sel == 4
    # 휙 넘기면 속도만큼 더 간다 (flick 160ms)
    choose.drag(Gesture("drag", (0, 0), (0, 0), 0, 20))
    choose.drag(Gesture("drag_end", (0, 0), (0, 0), 0, 20, 0.0, 1500.0))
    assert choose.sel == 4 - round((20 + 1500 * 0.16) / rh)


def test_choose_returns_to_idle_after_120s(app, choose):
    assert CHOOSE_IDLE_SEC == 120
    adv(app, 119.0)
    assert app.scene is choose
    adv(app, 1.5)
    assert isinstance(app.scene, IdleScene)


def test_key_and_tap_restart_the_120s(app, choose):
    adv(app, 100.0)
    step(app, key(pygame.K_RIGHT))
    adv(app, 100.0)
    assert app.scene is choose
    tap(app, _row(app, 4))
    adv(app, 100.0)
    assert app.scene is choose
    adv(app, 21.0)
    assert isinstance(app.scene, IdleScene)


# ---- 사진 고르기 · 다시 찍기 ----
from PIL import Image  # noqa: E402

from walnut.scenes.capture import CaptureScene, Shoot  # noqa: E402
from walnut.scenes.pick import PickScene, pick_layout  # noqa: E402
from walnut.scenes.retake import RetakeScene, retake_layout  # noqa: E402
from walnut.scenes.review import ReviewScene  # noqa: E402
from walnut.scenes.rows import RowScroll  # noqa: E402
from walnut.session import ShootSession  # noqa: E402


def make_shoot(app, n, total, extra=0):
    """컷 n 개짜리 프레임으로 total 장을 찍어 둔 촬영."""
    slots = [{"shot": k, "cx": 100, "cy": 100 + 200 * k, "w": 150, "h": 200} for k in range(n)]
    capture = dict(app.bundle.settings["capture"])
    capture["extra_shots"] = extra
    s = ShootSession({"slots": slots}, capture)
    s.shots = [Image.new("RGB", (640, 480), ((i * 37) % 255, 120, 160)) for i in range(total)]
    return Shoot(s, Image.new("RGBA", (400, 200 * n + 100)), None, False)


@pytest.fixture
def pick(app):
    sc = PickScene(app, make_shoot(app, 4, 6, extra=2))
    app.go(sc)
    step(app)
    app.fake_clock.t += 1
    return sc


def photo_pos(sc, i):
    return sc.lay.cells[i].center


def done_pos(sc):
    return sc.lay.done.center


def test_tap_photo_picks_and_moves_cursor(app, pick):
    tap(app, photo_pos(pick, 3))
    assert pick.shoot.session.pick_order()[3] == 0 and pick.cursor == 3
    tap(app, photo_pos(pick, 1))
    assert pick.shoot.session.pick_order()[1] == 1 and pick.cursor == 1
    tap(app, photo_pos(pick, 3))  # 다시 누르면 빠지고 뒤 순서가 당겨진다
    assert pick.shoot.session.pick_order()[3] is None and pick.shoot.session.pick_order()[1] == 0
    assert pick.cursor == 3


def test_tap_last_pick_moves_cursor_to_done_and_remote_continues(app, pick):
    for i in (0, 1, 2, 3):
        tap(app, photo_pos(pick, i))
    assert pick.cursor == 4 + 2 and pick.remote_state() == "G|0,1,2,3,-,-|6|4"
    step(app, key(pygame.K_UP))  # 리모컨으로 이어서
    assert pick.cursor == 5


def test_tap_done_ignored_until_complete(app, pick):
    tap(app, photo_pos(pick, 0))
    tap(app, done_pos(pick))
    assert app.scene is pick
    for i in (1, 2, 3):
        tap(app, photo_pos(pick, i))
    tap(app, done_pos(pick))
    assert isinstance(app.scene, ReviewScene)


def test_pick_tap_methods_directly(app, pick):
    pick.tap_done()
    assert app.scene is pick
    pick.tap_photo(2)
    assert pick.cursor == 2 and pick.shoot.session.pick_order()[2] == 0


def test_pick_tap_restarts_auto_timer(app, pick):
    auto = pick.auto
    adv(app, auto - 1)
    tap(app, photo_pos(pick, 0))
    adv(app, auto - 1)
    assert app.scene is pick
    adv(app, 2)
    assert isinstance(app.scene, ReviewScene)  # 무입력이면 채워서 넘어간다


def test_pick_layout_landscape_fits_grid_and_done(app):
    st = app.stage
    L = st.layout("pick")
    for total in (3, 6, 14, 20):
        lay = pick_layout(total, 3 / 4, st)
        assert lay.cols == min(L["cols"], total) and len(lay.cells) == total
        grid = pygame.Rect(L["grid"])
        for c in lay.cells:
            assert grid.contains(c)
        assert lay.done.size == tuple(L["done_button"])
        assert st.rect().contains(lay.done)
        assert lay.spans[-1][0] == lay.done.top


def test_pick_layout_portrait_picks_more_columns_when_larger():
    from walnut.booth_design import load
    from walnut.stage import geometry

    st = geometry(1080, 1920, load())
    lay = pick_layout(20, 3 / 4, st)
    assert lay.cols == 4 and st.rect().contains(lay.done)
    assert pick_layout(3, 3 / 4, st).cols == 3


def test_pick_with_18_photos_fits_so_drag_does_not_move(app):
    sc = PickScene(app, make_shoot(app, 4, 18, extra=14))
    app.go(sc)
    step(app)
    app.fake_clock.t += 1
    assert sc.scroll.overflow == 0
    sc.drag(Gesture("drag", (0, 0), (0, 0), 0, -300))
    sc.drag(Gesture("drag_end", (0, 0), (0, 0), 0, -300, 0.0, 0.0))
    assert sc.scroll.pos == 0 and sc.cursor == 0


def test_pick_keyboard_cols_follow_layout(app, pick):
    assert pick.cols == pick.lay.cols == 6
    step(app, key(pygame.K_DOWN))
    assert pick.cursor == 6  # 첫 줄만 있으니 [완료]


# ---- 줄 밀기 ----
def rows_scroll():
    sc = RowScroll(0.16)
    sc.set_rows([(100 + 300 * k, 200) for k in range(6)], 900)  # 내용 아래 끝 1800 → 넘침 900
    return sc


def test_row_scroll_shift_centers_row_and_clamps():
    sc = rows_scroll()
    assert sc.overflow == 900
    assert sc.shift_for(0) == 0                       # 중심 200 − 450 < 0
    assert sc.shift_for(2) == 800 - 450               # 중심 800
    assert sc.shift_for(5) == 900                     # 끝을 넘지 않는다
    sc.set_rows([(100, 200), (400, 200)], 900)
    assert sc.overflow == 0 and sc.shift_for(1) == 0  # 다 들어가면 밀지 않는다


def test_row_scroll_drag_follows_finger_and_snaps_nearest():
    sc = rows_scroll()
    assert sc.drag(Gesture("drag", (0, 0), (0, 0), 0, -260)) is None
    assert sc.pos == 260
    r = sc.drag(Gesture("drag_end", (0, 0), (0, 0), 0, -260, 0.0, 0.0))
    assert r == 2 and sc.row == 2                      # 후보 0, 50, 350, 650, 900, 900 중 350
    sc.update(5.0)
    assert sc.pos == sc.shift_for(2)
    # 휙 넘기면 속도만큼 더 간다
    sc.drag(Gesture("drag", (0, 0), (0, 0), 0, -50))
    assert sc.drag(Gesture("drag_end", (0, 0), (0, 0), 0, -50, 0.0, -2000.0)) == 3  # 350+50+320 = 720 → 650


# ---- 다시 찍기 ----
def make_retake(app, n):
    shoot = make_shoot(app, n, n)
    sc = RetakeScene(app, shoot, Image.new("RGB", (100, 100)))
    app.go(sc)
    step(app)
    app.fake_clock.t += 1
    return sc


@pytest.fixture
def retake(app):
    return make_retake(app, 4)


def cut_pos(sc, i):
    c = sc.lay.cuts[i]
    return (c.centerx, c.top + 20)


def test_tap_cut_toggles_and_moves_cursor(app, retake):
    tap(app, cut_pos(retake, 2))
    assert retake.keep == [True, True, False, True] and retake.cursor == 2 and retake.row == 0
    assert retake.remote_state() == "P|1101|2|0|0"
    tap(app, cut_pos(retake, 2))
    assert retake.keep == [True] * 4


def test_tap_retake_ignored_without_cuts_to_redo(app, retake):
    tap(app, retake.lay.start.center)
    assert app.scene is retake and retake.row == 0
    retake.tap_retake()
    assert app.scene is retake and retake.shoot.session.retake_queue == []


def test_tap_retake_starts_only_unkept(app, retake):
    tap(app, cut_pos(retake, 1))
    tap(app, cut_pos(retake, 3))
    tap(app, retake.lay.start.center)
    assert isinstance(app.scene, CaptureScene)
    assert retake.shoot.session.retake_queue == [1, 3]


def test_tap_cancel_returns_to_review(app, retake):
    tap(app, retake.lay.cancel.center)
    assert isinstance(app.scene, ReviewScene)


def test_retake_methods_directly(app, retake):
    retake.tap_cut(0)
    assert retake.keep[0] is False
    retake.tap_back()
    assert isinstance(app.scene, ReviewScene)


def test_retake_tap_then_remote_continues(app, retake):
    tap(app, cut_pos(retake, 1))
    step(app, key(pygame.K_RIGHT))
    assert retake.cursor == 2 and retake.remote_state() == "P|1011|2|0|0"


def test_retake_tap_restarts_auto_timer(app, retake):
    adv(app, retake.auto - 1)
    assert retake.idle_t >= retake.auto - 1
    tap(app, cut_pos(retake, 0))
    assert retake.idle_t < 0.1  # 탭이 타이머를 처음으로 되돌렸다
    adv(app, retake.auto - 1)
    assert app.scene is retake


def test_retake_layout_landscape_follows_tokens(app):
    st = app.stage
    L = st.layout("retake")
    lay = retake_layout([3 / 4] * 4, st)
    assert lay.cols == L["cols"] and len(lay.cuts) == 4
    for c in lay.cuts:
        assert c.w <= L["thumb_box"][0] and c.h <= L["thumb_box"][1]
    assert lay.start.size == tuple(L["button_sizes"][0]) and lay.cancel.size == tuple(L["button_sizes"][1])
    assert lay.start.centerx == L["button_centers_x"][0] and lay.start.centery == L["buttons_y"]
    assert lay.scroll_over == 0


def test_retake_layout_portrait_stacks_buttons():
    from walnut.booth_design import load
    from walnut.stage import geometry

    st = geometry(1080, 1920, load())
    lay = retake_layout([3 / 4] * 4, st)
    assert lay.cols == 2 and lay.start.centerx == lay.cancel.centerx
    assert lay.cancel.top > lay.start.bottom
    assert st.rect().contains(lay.start) and st.rect().contains(lay.cancel)


def test_retake_with_18_cuts_drag_moves_rows_and_keys_follow(app):
    sc = make_retake(app, 18)
    assert sc.scroll.overflow > 0 and len(sc.lay.spans) == 5 + 1
    top = sc.lay.cuts[0].top
    sc.drag(Gesture("drag", (0, 0), (0, 0), 0, -400))
    assert sc.scroll.pos > 0
    sc.drag(Gesture("drag_end", (0, 0), (0, 0), 0, -400, 0.0, 0.0))
    r = sc.scroll.row
    assert r > 0
    assert sc.row == 0 and (sc.cursor // sc.lay.cols == r or r == 5)
    adv(app, 2.0)
    assert sc.scroll.pos == sc.scroll.shift_for(r)
    # 끝까지 끌면 끝에 닿는 줄 (웹과 같이 같은 거리면 지금 줄을 지킨다)
    sc.drag(Gesture("drag", (0, 0), (0, 0), 0, -9000))
    sc.drag(Gesture("drag_end", (0, 0), (0, 0), 0, -9000, 0.0, 0.0))
    assert sc.scroll.shift_for(sc.scroll.row) == sc.scroll.overflow
    assert sc.lay.cuts[0].top == top  # 배치 자체는 밀리지 않는다 (그릴 때만 민다)
    # 버튼 줄에서 끝까지 끌면 버튼 줄로 남고 [다시 찍기] 가 고른 버튼이 된다
    step(app, key(pygame.K_DOWN))
    assert sc.row == 1 and sc.scroll.row == len(sc.lay.spans) - 1
    sc.drag(Gesture("drag", (0, 0), (0, 0), 0, -9000))
    sc.drag(Gesture("drag_end", (0, 0), (0, 0), 0, -9000, 0.0, 0.0))
    assert sc.row == 1 and sc.btn == 0
    # 키로 컷 줄로 올라오면 그 줄로 민다
    step(app, key(pygame.K_UP))
    assert sc.row == 0 and sc.scroll.row == sc.cursor // sc.lay.cols


def test_retake_few_cuts_drag_does_nothing(app, retake):
    retake.drag(Gesture("drag", (0, 0), (0, 0), 0, -300))
    retake.drag(Gesture("drag_end", (0, 0), (0, 0), 0, -300, 0.0, 0.0))
    assert retake.scroll.pos == 0 and retake.cursor == 0


# ---- 완성 확인 · 공유 · 인쇄 매수 ----
from walnut.scenes.idle import IdleScene as _Idle  # noqa: E402
from walnut.scenes.print_copies import PrintCopiesScene  # noqa: E402
from walnut.scenes.retake import RetakeScene as _Retake  # noqa: E402
from walnut.scenes.share import ShareScene, finish  # noqa: E402


@pytest.fixture
def review(app):
    shoot = make_shoot(app, 3, 3)
    sc = ReviewScene(app, shoot)
    app.go(sc)
    step(app)
    app.fake_clock.t += 1
    return sc


def test_review_qr_button_tap_acts_at_once(app, review):
    tap(app, review.lay.buttons[0].center)
    assert isinstance(app.scene, ShareScene)


def test_review_retake_button_tap_acts_at_once(app, review):
    assert len(review.buttons) == 2
    tap(app, review.lay.buttons[1].center)
    assert isinstance(app.scene, _Retake)


def test_review_press_is_shared_by_key_and_tap(app, review):
    review.press("retake")
    assert isinstance(app.scene, _Retake)


def test_review_tap_anywhere_resets_idle_timer(app, review):
    adv(app, 5.0)
    assert review.idle_t >= 5.0
    tap(app, (700, 1040))  # 버튼 밖 (구석은 관리자 패널 자리)
    assert review.idle_t < 0.1  # 한 프레임만 셌다 (5초가 지워짐)
    assert app.scene is review


def test_review_cursor_follows_tap_then_remote_continues(app, review):
    review.press("retake")  # 장면이 바뀌어도 커서는 눌린 버튼
    assert review.sel == 1


def test_share_tap_anywhere_skips(app, review):
    review.skip()
    sc = app.scene
    assert isinstance(sc, ShareScene)
    step(app)
    app.fake_clock.t += 1
    tap(app, (700, 1040))
    assert isinstance(app.scene, _Idle)


def test_share_tap_goes_to_print_copies_when_printing(app, review):
    app.bundle.settings["print"]["enabled"] = True
    review.skip()
    step(app)
    app.fake_clock.t += 1
    tap(app, (900, 900))
    assert isinstance(app.scene, PrintCopiesScene)


@pytest.fixture
def copies(app):
    app.bundle.settings["print"]["copies_max"] = 3
    sc = PrintCopiesScene(app, Image.new("RGB", (400, 600)), "tok")
    app.go(sc)
    step(app)
    app.fake_clock.t += 1
    return sc


def test_set_copies_clamps(copies):
    copies.set_copies(0)
    assert copies.copies == 1
    copies.set_copies(9)
    assert copies.copies == 3
    copies.set_copies(2)
    assert copies.copies == 2


def test_plus_minus_taps_stay_within_range(app, copies):
    tap(app, copies.lay.less.center)
    assert copies.copies == 1
    for _ in range(5):
        tap(app, copies.lay.more.center)
    assert copies.copies == 3
    tap(app, copies.lay.less.center)
    assert copies.copies == 2
    assert copies.remote_state() == "Q|2|3"


def test_confirm_tap_prints_then_home(app, copies, monkeypatch):
    calls = []
    monkeypatch.setattr(app.printer, "print", lambda img, n, token="", url=None: calls.append((n, token)))
    tap(app, copies.lay.more.center)
    tap(app, copies.lay.confirm.center)
    assert calls == [(2, "tok")]
    assert not isinstance(app.scene, PrintCopiesScene)


def test_copies_taps_reset_idle_timer(app, copies):
    adv(app, 10.0)
    assert copies.idle_t >= 10.0
    tap(app, copies.lay.more.center)
    assert copies.idle_t < 0.1
    adv(app, 10.0)
    tap(app, (700, 1040))  # 아무 데나
    assert copies.idle_t < 0.1 and app.scene is copies


def test_copies_key_flow_unchanged(app, copies, monkeypatch):
    step(app, key(pygame.K_UP), key(pygame.K_UP), key(pygame.K_UP))
    assert copies.copies == 3
    step(app, key(pygame.K_DOWN))
    assert copies.copies == 2


# ---- 숫자 입력 · 페어링 ----
from walnut.scenes.dial import DigitDial  # noqa: E402
from walnut.scenes.pairing import PairingScene  # noqa: E402
from tests.test_app import ENTER, ESC, digits  # noqa: E402,F401


@pytest.fixture
def pairing(make_app):
    a = make_app()
    a.time_fn = clock = FakeClock()
    a.fake_clock = clock
    a._went_at = clock.t - 10
    step(a)
    assert isinstance(a.scene, PairingScene)
    return a


def pad_pos(owner, cols: int, key: str):
    """owner(장면 · 관리자 패널)가 마지막에 등록한 숫자 패드 12칸에서 key 칸의 가운데."""
    order = (list("123456789") + ["back", "0", "ok"]) if cols == 3 else (list("1234567890") + ["back", "ok"])
    rect = owner.hits._items[-12:][order.index(key)][0]
    return rect.center


def pad(app, owner, key: str, cols: int = 12):
    app.fake_clock.t += 1
    tap(app, pad_pos(owner, cols, key))


def test_dial_methods_are_shared_paths():
    got = []
    d = DigitDial(3)
    d.on_submit = got.append
    d.press_digit(4)
    d.press_digit(8)
    assert d.digits == [4, 8, None] and d.cursor == 2
    d.confirm()  # 다 차지 않았으면 제출하지 않는다
    assert got == []
    d.press_digit(2)
    d.backspace()
    assert d.entered() == 2
    d.press_digit(7)
    d.confirm()
    assert got == ["487"]


def test_pairing_pad_fills_cells_and_continues_with_keys(pairing):
    s = pairing.scene
    pad(pairing, s, "4")
    pad(pairing, s, "8")
    step(pairing, *digits("2"))  # 키보드가 같은 칸에서 이어진다
    assert s.dial.digits[:3] == [4, 8, 2] and s.dial.cursor == 3
    assert s.remote_state() == "N|3|8"


def test_pairing_pad_back_erases(pairing):
    s = pairing.scene
    pad(pairing, s, "4")
    pad(pairing, s, "8")
    pad(pairing, s, "back")
    assert s.dial.entered() == 1 and s.dial.digits[1] is None


def test_pairing_pad_ok_submits_only_when_full(pairing):
    s = pairing.scene
    got = []
    s.dial.on_submit = got.append
    for c in "1234567":
        pad(pairing, s, c)
    pad(pairing, s, "ok")
    assert got == []
    pad(pairing, s, "8")
    pad(pairing, s, "ok")
    assert got == ["12345678"]


def test_pairing_pad_continues_after_dial_up_down(pairing):
    s = pairing.scene
    step(pairing, key(pygame.K_UP))            # 첫 칸 0
    step(pairing, key(pygame.K_RIGHT))
    pad(pairing, s, "5")                        # 둘째 칸에 넣고 셋째로
    assert s.dial.digits[:2] == [0, 5] and s.dial.cursor == 2
    step(pairing, key(pygame.K_LEFT), key(pygame.K_DOWN))  # 둘째 칸 5 → 4
    pad(pairing, s, "9")
    assert s.dial.digits[:3] == [0, 9, None] and s.dial.cursor == 2


def test_pairing_cell_tap_moves_cursor(pairing):
    s = pairing.scene
    for c in "123":
        pad(pairing, s, c)
    first = s.hits._items[1][0].center  # 첫 등록은 '연결 없이 시작' 버튼, 그다음이 첫 칸
    pairing.fake_clock.t += 1
    tap(pairing, first)
    assert s.dial.cursor == 0


def test_pairing_pad_ignored_while_busy(pairing):
    s = pairing.scene
    pad(pairing, s, "4")
    s.busy = True
    pad(pairing, s, "8")
    pad(pairing, s, "back")
    assert s.dial.entered() == 1 and s.dial.cursor == 1


def test_pairing_pad_ignored_without_server(make_app):
    a = make_app({"SERVER_URL": ""})
    a.time_fn = a.fake_clock = FakeClock()
    a._went_at = a.fake_clock.t - 10
    step(a)
    assert isinstance(a.scene, PairingScene)
    pad(a, a.scene, "4")
    assert a.scene.dial.entered() == 0


def test_pairing_portrait_uses_three_column_pad(make_app):
    a = make_app(display_size=(1080, 1920))
    a.time_fn = a.fake_clock = FakeClock()
    a._went_at = a.fake_clock.t - 10
    step(a)
    pad(a, a.scene, "7", cols=3)
    pad(a, a.scene, "0", cols=3)
    assert a.scene.dial.digits[:2] == [7, 0]


def test_pairing_hint_follows_input_kind(pairing):
    s = pairing.scene
    from walnut.scenes.pairing import HINT_KEY, HINT_LOCAL, HINT_TOUCH
    pad(pairing, s, "1")
    assert pairing.input_kind != "key" and s.hint() == HINT_TOUCH
    step(pairing, key(pygame.K_UP))
    assert pairing.input_kind == "key" and s.hint() == HINT_KEY + HINT_LOCAL
    pad(pairing, s, "1")
    assert pairing.input_kind != "key" and s.hint() == HINT_TOUCH


def test_admin_pin_pad_enters_masked_digits(make_app, paired_with_bundle):
    a = make_app()
    a.time_fn = a.fake_clock = FakeClock()
    a._went_at = a.fake_clock.t - 10
    step(a, ESC)
    assert a.admin.mode == "pin"
    for c in "482":
        pad(a, a.admin, c)
    assert a.admin.dial.entered() == 3 and a.admin.dial.masked
    assert a.admin.dial.cursor == 3


def test_locked_dial_keys_still_work_but_pad_and_cells_are_inert():
    d = DigitDial(3)
    d.locked = lambda: True
    d.handle(key(pygame.K_5, "5"))             # 키는 예전 그대로
    assert d.digits[0] == 5 and d.cursor == 1
    d.handle(key(pygame.K_BACKSPACE, "\b"))
    assert d.digits[0] is None
    d._press("7")                               # 패드 · 칸 탭은 아무 일도 없다
    d._press("back")
    d._move_to(2)
    assert d.entered() == 0 and d.cursor == 0
    got = []
    d.on_submit = got.append
    d.digits = [1, 2, 3]
    d._press("ok")
    assert got == []
    d.handle(ENTER)
    assert got == ["123"]


def test_masked_dial_hides_digits_outside_cursor(pairing, monkeypatch):
    from walnut import ui as ui_mod
    d = DigitDial(6, masked=True)
    for n in (4, 8, 2):
        d.press_digit(n)
    drawn = []
    real = ui_mod.text
    monkeypatch.setattr(ui_mod, "text", lambda surf, s, *a, **k: (drawn.append(s), real(surf, s, *a, **k))[1])
    st = pairing.stage
    d._draw_cells(pygame.Surface((1920, 1080)), st, pairing.theme.roles, lambda r, f: None, (960, 400), 100, st.layout("dial"))
    assert drawn == []                           # 세 칸 모두 점으로만 보인다


# ---- 관리자 패널 · 비상 번들 (Task 13) ----
from tests.test_app import ENTER, Q, digits, paired  # noqa: E402,F401
from walnut.scenes.import_zip import ImportZipScene  # noqa: E402
from walnut.scenes.waiting import WaitingScene as _Waiting  # noqa: E402


def _open_panel(app):
    step(app, ESC, *digits("482916"), ENTER)
    assert app.admin.mode == "panel"
    step(app)  # 그려서 버튼 영역을 등록
    app.fake_clock.t += 1


def _tap_btn(app, name):
    step(app)
    app.fake_clock.t += 1
    tap(app, app.admin.rects[name].center)


def _in_choose(app):
    app.go(ChooseScene(app, "F", [(f, f) for f in ("a", "b")]))
    step(app)
    app.fake_clock.t += 1


def test_panel_home_closes_and_goes_idle(app):
    _in_choose(app)
    _open_panel(app)
    _tap_btn(app, "home")
    assert app.admin is None and isinstance(app.scene, IdleScene)


def test_panel_next_closes_and_calls_scene_skip(app):
    _in_choose(app)
    skipped = []
    app.scene.skip = lambda: skipped.append(1)
    _open_panel(app)
    _tap_btn(app, "next")
    assert app.admin is None and skipped == [1]


def test_home_next_disabled_on_idle(app):
    assert isinstance(app.scene, IdleScene)
    skipped = []
    app.scene.skip = lambda: skipped.append(1)
    _open_panel(app)
    assert app.admin.buttons() == ["sync", "import", "unpair", "home", "next"]
    assert not app.admin.enabled("home") and not app.admin.enabled("next")
    _tap_btn(app, "home")
    _tap_btn(app, "next")
    assert app.admin is not None and skipped == [] and isinstance(app.scene, IdleScene)
    # 키: 끝에서 돌아도 쓸 수 없는 버튼에는 멈추지 않는다
    right = key(pygame.K_RIGHT)
    step(app, right, right, right)
    assert app.admin.cursor == 0


def test_enabled_home_next_reachable_by_keys(app):
    _in_choose(app)
    _open_panel(app)
    step(app, key(pygame.K_LEFT))
    assert app.admin.buttons()[app.admin.cursor] == "next"
    step(app, ENTER)
    assert app.admin is None


def test_limited_panel_has_no_home_next(make_app, paired):
    a = make_app()
    a.time_fn = a.fake_clock = FakeClock()
    a._went_at = a.fake_clock.t - 10
    step(a, ESC)
    assert a.admin.mode == "limited" and a.admin.buttons() == ["import"]
    step(a)
    assert "home" not in a.admin.rects and "next" not in a.admin.rects
    assert "close" in a.admin.rects and "quit" in a.admin.rects


def test_quit_and_close_reachable_by_touch(app):
    # 키보드 없는 설치: 길게 누르기로 열리지 않아도 패널이 열린 뒤 닫기 · 종료는 탭으로
    _open_panel(app)
    _tap_btn(app, "close")
    assert app.admin is None
    _open_panel(app)
    _tap_btn(app, "quit")
    assert app.running and app.admin.quit_label() == "한 번 더 누르면 종료"
    _tap_btn(app, "quit")
    assert not app.running


def test_pin_mode_has_close_only(app):
    step(app, ESC)
    step(app)
    assert app.admin.mode == "pin" and "quit" not in app.admin.rects
    _tap_btn(app, "close")
    assert app.admin is None


def test_quit_only_mode_touch_close_and_quit(make_app):
    a = make_app()
    a.time_fn = a.fake_clock = FakeClock()
    a._went_at = a.fake_clock.t - 10
    step(a, ESC)
    assert a.admin.mode == "quit_only"
    step(a)
    assert "home" not in a.admin.rects
    _tap_btn(a, "quit")
    _tap_btn(a, "quit")
    assert not a.running


def test_unpair_tap_still_double_confirms(app):
    _open_panel(app)
    _tap_btn(app, "unpair")
    assert app.device is not None
    _tap_btn(app, "unpair")
    assert app.device is None


def test_panel_background_is_light_card(app):
    _open_panel(app)
    r = app.admin.rects["panel"]
    px = app.screen.get_at((r.x + 20, r.centery))[:3]
    # ui.panel 의 확대·축소 때문에 1~4 정도 어두워질 수 있다 — 막 · 어두운 면이 아니라 배경색 카드인지만 본다
    assert all(abs(a - b) <= 4 for a, b in zip(px, app.theme.roles["background_top"][:3]))


def _import_scene(app, monkeypatch, n=2):
    from pathlib import Path
    import walnut.scenes.import_zip as mod
    monkeypatch.setattr(mod, "find_zips", lambda dirs: [Path(f"/x/f{i}.zip") for i in range(n)])
    sc = ImportZipScene(app)
    app.go(sc)
    step(app)
    app.fake_clock.t += 1
    return sc


def test_import_tap_item_imports_like_enter(app, monkeypatch):
    sc = _import_scene(app, monkeypatch)
    got = []
    app.import_zip = lambda p: got.append(p.name) or 7
    sc.tap_item(1)
    assert sc.sel == 1 and got == ["f1.zip"] and sc.done
    sc.tap_item(0)  # 끝난 뒤 줄 탭은 Enter 와 같이 처음 화면으로
    step(app)
    assert isinstance(app.scene, IdleScene)


def test_import_tap_back_row_goes_home(app, monkeypatch):
    sc = _import_scene(app, monkeypatch)
    sc.tap_item(2)
    assert isinstance(app.scene, IdleScene)


def test_import_row_tap_via_hit(app, monkeypatch):
    sc = _import_scene(app, monkeypatch)
    got = []
    app.import_zip = lambda p: got.append(p.name) or 7
    tap(app, sc.rows[0].center)
    assert got == ["f0.zip"]


def test_import_failed_tap_shows_message(app, monkeypatch):
    from walnut.bundle import ZipImportError
    sc = _import_scene(app, monkeypatch)

    def bad(p):
        raise ZipImportError("bad_signature")
    app.import_zip = bad
    sc.tap_item(0)
    assert "서명" in sc.message and not sc.done


def test_waiting_status_wording_follows_input_kind(make_app, tmp_path, fake_server):
    _save_device(tmp_path, fake_server.url)
    a = make_app()
    a.time_fn = FakeClock()
    step(a)
    w = a.scene
    assert isinstance(w, _Waiting)
    a.sync = None
    a.input_kind = "key"
    assert "ESC" in w.status()
    a.input_kind = "touch"
    assert w.status() == "서버 주소가 없어요 — 왼쪽 위를 길게 눌러 관리자 패널에서 번들 파일을 가져오세요"


# ---- 합성 시간 측정 (BOOTH_CAPTURE_LOG) — 완료 때 result 줄 (예전 baseline 줄 대신) ----
def _metric_lines(app):
    path = app.cfg.data_dir / "logs" / "capture_metrics.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_review_compose_time_goes_into_result_line(make_app, paired_with_bundle):
    app = make_app({"BOOTH_CAPTURE_LOG": "1"})
    app.time_fn = FakeClock()
    app.fps = 29.5
    app.camera.fps = 24.0
    shoot = make_shoot(app, 3, 3)
    sc = ReviewScene(app, shoot)
    assert _metric_lines(app) == []  # 합성 때는 쓰지 않는다
    assert shoot.compose_ms is not None and shoot.compose_ms >= 0
    sc.skip()
    (rec,) = _metric_lines(app)
    assert rec["type"] == "result" and rec["compose_ms"] >= 0 and rec["cuts"] == 3 and rec["retakes"] == 0
    assert rec["collage"] == [sc.collage.width, sc.collage.height]
    assert rec["display_fps"] == 29.5 and rec["camera_fps"] == 24.0


def test_review_with_existing_collage_logs_nothing(make_app, paired_with_bundle):
    app = make_app({"BOOTH_CAPTURE_LOG": "1"})
    shoot = make_shoot(app, 3, 3)
    ReviewScene(app, shoot, Image.new("RGB", (400, 700)))
    assert _metric_lines(app) == [] and shoot.compose_ms is None


def test_review_without_capture_log_creates_no_file(make_app, paired_with_bundle):
    app = make_app()
    ReviewScene(app, make_shoot(app, 3, 3))
    assert not (app.cfg.data_dir / "logs" / "capture_metrics.jsonl").exists()


# ---- 영수증 프린터: 공유 주소 넘기기 · 관리자 패널 상태 · 시험 인쇄 ----

from types import SimpleNamespace  # noqa: E402

from walnut.printer import ReceiptPrinter  # noqa: E402

PRINTER_PORTS = [SimpleNamespace(device="COM9", vid=0x1CBE, pid=0x0002)]


def test_confirm_passes_share_url(app, monkeypatch):
    calls = []
    monkeypatch.setattr(app.printer, "print",
                        lambda img, n, token="", url=None: calls.append((n, token, url)))
    sc = PrintCopiesScene(app, Image.new("RGB", (400, 600)), "tok", url="https://x/p/tok")
    app.go(sc)
    sc.confirm()
    assert calls == [(1, "tok", "https://x/p/tok")]


def test_share_hands_url_to_print_copies(app):
    app.bundle.settings["print"]["enabled"] = True
    sc = ShareScene(app, Image.new("RGB", (400, 600)), "tok", "https://x/p/tok")
    app.go(sc)
    sc.skip()
    assert isinstance(app.scene, PrintCopiesScene) and app.scene.url == "https://x/p/tok"


def _receipt(app, setting="", ports=PRINTER_PORTS):
    app.printer = ReceiptPrinter(setting, ports=ports, start=False)
    return app.printer


def _printer_line(app):
    from walnut.scenes.admin import AdminPanel
    return [x for x in AdminPanel(app)._status_lines() if x.startswith("프린터")]


def test_panel_status_line_for_each_printer(app):
    assert _printer_line(app) == ["프린터  더미 (파일로 저장)"]
    _receipt(app)
    assert _printer_line(app) == ["프린터  COM9 연결됨 · 대기 0"]
    _receipt(app, ports=[])
    assert _printer_line(app) == ["프린터  연결 안 됨"]
    _receipt(app, setting="off")
    assert _printer_line(app) == ["프린터  꺼짐"]


def test_panel_print_test_button_sends_one(app):
    p = _receipt(app)
    _open_panel(app)
    assert app.admin.buttons() == ["sync", "print_test", "import", "unpair", "home", "next"]
    _tap_btn(app, "print_test")
    assert app.admin.message == "시험 인쇄를 보냈어요" and p.pending() == 1


def test_panel_print_test_without_printer(app):
    _receipt(app, ports=[])
    _open_panel(app)
    _tap_btn(app, "print_test")
    assert app.admin.message == "프린터를 찾지 못했어요"


def test_panel_has_no_print_test_with_dummy(app):
    _open_panel(app)
    assert "print_test" not in app.admin.buttons()


def test_panel_action_row_fits_with_print_test(app):
    _receipt(app)
    _open_panel(app)
    _tap_btn(app, "unpair")                          # '한 번 더 누르면 해제' — 가장 긴 상태
    step(app)
    box = app.admin.rects["panel"]
    pad = app.stage.layout("admin")["pad"][0]
    for n in ("sync", "print_test", "import", "unpair"):
        r = app.admin.rects[n]
        assert box.x + pad <= r.left and r.right <= box.right - pad, n
