"""연결 없이 시작 — 페어링 없이 기본 번들로 쓰는 '로컬 사용'."""

from __future__ import annotations

import pygame
import pytest

from walnut import ui
from walnut.bundle import BundleStore
from walnut.device import Device, DeviceStore

KEY = b"k" * 32
DT = 0.25
FAST = {"capture": {"countdown_sec": 3, "between_sec": 0}, "filters": {"enabled": ["original"]}}


def key(k: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode="", mod=0, scancode=0)


ENTER, TAB, ESC, F5 = (key(k) for k in (pygame.K_RETURN, pygame.K_TAB, pygame.K_ESCAPE, pygame.K_F5))


def step(app, *events, dt: float = 1 / 60) -> None:
    app.step(dt, list(events))


def run(app, secs: float, dt: float = DT) -> None:
    for _ in range(int(round(secs / dt))):
        app.step(dt, [])


def name(app) -> str:
    return type(app.scene).__name__


@pytest.fixture
def drawn(monkeypatch):
    """화면에 그려진 글자를 모은다."""
    texts: list[str] = []
    orig = ui.text

    def spy(surf, text, *a, **k):
        texts.append(text)
        return orig(surf, text, *a, **k)

    monkeypatch.setattr(ui, "text", spy)
    return texts


def test_tab_starts_local(make_app):
    app = make_app()
    assert name(app) == "PairingScene" and app.local is False
    step(app, TAB)
    assert name(app) == "IdleScene" and app.local and app.device is None
    assert app.bundle.event_id == 0 and len(app.bundle.frames) == 1


def test_local_works_without_server_url(make_app):
    app = make_app({"SERVER_URL": ""})
    step(app, TAB)
    assert name(app) == "IdleScene"


def test_tap_on_button_starts_local(make_app):
    app = make_app()
    step(app)
    app.scene.hits.tap(app.scene.local_rect().center)
    assert name(app) == "IdleScene" and app.local


def test_local_button_is_inside_the_screen(make_app):
    for size in ((1920, 1080), (1080, 1920)):
        app = make_app(display_size=size)
        assert pygame.Rect(0, 0, app.stage.w, app.stage.h).contains(app.scene.local_rect())


def test_busy_pairing_ignores_tab(make_app):
    app = make_app()
    app.scene.busy = True
    step(app, TAB)
    assert name(app) == "PairingScene" and app.local is False


def test_pairing_hint_mentions_tab(make_app):
    app = make_app()
    assert "Tab 연결 없이 시작" in app.scene.hint()


def test_local_shoot_saves_on_this_pc(make_app, tmp_path):
    app = make_app()
    app.start_local(FAST)
    step(app, ENTER)  # 필터 · 프레임이 하나씩이라 바로 촬영
    assert name(app) == "CaptureScene"
    run(app, 4 * 3 + DT)
    assert name(app) == "ReviewScene"
    step(app, ENTER)
    assert name(app) == "ShareScene" and app.scene.url is None
    files = list((tmp_path / "data" / "collage").glob("0_*.jpg"))
    assert len(files) == 1 and app.uploader.pending() == 0


def test_local_is_not_remembered(make_app, tmp_path):
    make_app().start_local()
    assert name(make_app()) == "PairingScene"
    assert not (tmp_path / "data" / "device.json").exists()
    assert BundleStore(tmp_path / "data").current() is None


def test_f5_in_local_stays_local(make_app):
    app = make_app()
    app.start_local(FAST)
    step(app, ENTER)
    assert name(app) == "CaptureScene"
    step(app, F5)
    assert name(app) == "IdleScene" and app.local


def test_admin_local_mode(make_app):
    app = make_app()
    app.start_local()
    step(app, ESC)
    assert app.admin.mode == "local" and app.admin.buttons() == ["pair", "home", "next"]
    step(app)  # 패널 그리기가 예외 없이 끝난다
    assert app.admin is not None
    app.admin._activate("pair")
    assert app.admin is None and name(app) == "PairingScene" and app.local is False and app.bundle is None


def test_admin_before_local_is_still_quit_only(make_app):
    app = make_app()
    step(app, ESC)
    assert app.admin.mode == "quit_only"


def test_long_press_opens_admin_in_local(make_app):
    from walnut.touch import Gesture

    app = make_app()
    app._gesture(Gesture("long", (10, 10), (10, 10)))
    assert app.admin is None  # 페어링 전 · 로컬 아님
    app.start_local()
    app._gesture(Gesture("long", (10, 10), (10, 10)))
    assert app.admin is not None and app.admin.mode == "local"


def test_pairing_ends_local(make_app, fake_server):
    app = make_app()
    app.start_local()
    app.on_paired(Device(fake_server.url, "tok", KEY, 7, "행사"))
    assert app.local is False and name(app) == "WaitingScene" and app.bundle is None


def test_idle_shows_local_note_only_in_local(make_app, make_bundle, tmp_path, fake_server, drawn):
    app = make_app()
    app.start_local()
    step(app)
    assert app.local_note() in drawn and name(app) == "IdleScene"

    DeviceStore(tmp_path / "data" / "device.json").save(Device(fake_server.url, "tok", KEY, 1, "테스트 행사"))
    store = BundleStore(tmp_path / "data")
    raw, assets = make_bundle(version=1)
    store.stage(raw, assets.__getitem__)
    store.activate(1)
    paired = make_app()
    drawn.clear()
    step(paired)
    assert name(paired) == "IdleScene" and paired.local_note() not in drawn


def test_local_idle_hides_the_qr_privacy_line(make_app, drawn):
    """기본 개인정보 문구(QR · 72시간 보관)는 연결 없이 쓸 때 사실이 아니다 — 위의 안내만 보인다."""
    app = make_app()
    app.start_local()
    step(app)
    assert app.theme.privacy_text and app.theme.privacy_text not in drawn
    assert app.local_note() in drawn
