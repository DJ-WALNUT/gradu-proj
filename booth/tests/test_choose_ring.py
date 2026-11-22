"""고르기 화면 — 고른 항목의 포커스 테두리가 목록 창 끝에서 잘리지 않는다."""

from __future__ import annotations

import pygame
import pytest

from test_flow import DOWN, ENTER, KEY, name, step
from walnut.bundle import BundleStore
from walnut.device import Device, DeviceStore

FAST = {"capture": {"countdown_sec": 3, "between_sec": 0}}


@pytest.fixture
def app_with_bundle(make_app, make_bundle, tmp_path, fake_server):
    """app_with_bundle(settings_patch, display_size) → 페어링 + 번들이 적용된 App (대기 화면, 필터 6개)."""
    def _make(settings_patch=None, display_size=(1920, 1080)):
        DeviceStore(tmp_path / "data" / "device.json").save(Device(fake_server.url, "tok", KEY, 1, "테스트 행사"))
        store = BundleStore(tmp_path / "data")
        raw, assets = make_bundle(version=1, settings_patch=settings_patch)
        store.stage(raw, assets.__getitem__)
        store.activate(1)
        app = make_app(display_size=display_size)
        step(app)
        assert name(app) == "IdleScene"
        return app

    return _make


def _ring_rows(app, item: pygame.Rect) -> tuple[int, int]:
    """항목 위 · 아래 포커스 테두리 띠의 바깥쪽 줄 (y 좌표)."""
    tk = app.stage.tokens
    out = tk["space"]["step"][0] + tk["touch"]["focus_ring_px"]  # 버튼에서 테두리 바깥 끝까지
    return item.top - out + 1, item.bottom + out - 2


def _is_ring(app, pos) -> bool:
    got = app.screen.get_at(pos)[:3]
    want = tuple(app.theme.roles["line"][:3])
    return all(abs(a - b) <= 12 for a, b in zip(got, want))


@pytest.mark.parametrize("size", [(1920, 1080), (1080, 1920)])
def test_first_item_focus_ring_is_not_clipped(app_with_bundle, size):
    app = app_with_bundle(FAST, display_size=size)
    step(app, ENTER)  # 대기 → 필터 고르기 (키보드 입력 → 포커스 테두리가 보인다)
    assert name(app) == "ChooseScene" and app.scene.kind == "F" and app.scene.sel == 0
    step(app)
    item = app.scene.hits._items[0][0]  # 첫 항목 (맨 위 칸)
    top, _ = _ring_rows(app, item)
    assert _is_ring(app, (item.centerx, top)), "맨 위 항목의 테두리 윗줄이 잘렸다"
    assert _is_ring(app, (item.centerx, item.top - app.stage.tokens["space"]["step"][0] - 1))


def test_last_visible_item_focus_ring_is_not_clipped(app_with_bundle):
    app = app_with_bundle(FAST)  # 가로: 필터 6개가 한 창에 다 보인다 → 마지막이 창 맨 아래 칸
    step(app, ENTER)
    for _ in range(5):
        step(app, DOWN)
    assert app.scene.sel == 5
    for _ in range(60):  # 미끄러지는 연출이 있으면 끝날 때까지
        step(app)
    item = app.scene.hits._items[5][0]
    _, bottom = _ring_rows(app, item)
    assert _is_ring(app, (item.centerx, bottom)), "맨 아래 항목의 테두리 아랫줄이 잘렸다"
