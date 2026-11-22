"""앱 골격: 시작 장면, 페어링, 번들 교체, 연결 해제, 장면 오류 복구, 관리자 패널, zip 가져오기."""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import time
import zipfile

import pygame
import pytest
from PIL import Image

from walnut.bundle import BundleStore
from walnut.device import Device, DeviceStore
from walnut.scenes.base import Scene
from walnut.scenes.dial import DigitDial

KEY = b"k" * 32


# ---- 도우미 ----

def key(k: int, ch: str = "") -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode=ch, mod=0, scancode=0)


def digits(s: str) -> list[pygame.event.Event]:
    return [key(getattr(pygame, f"K_{c}"), c) for c in s]


ENTER = key(pygame.K_RETURN, "\r")
ESC = key(pygame.K_ESCAPE, "\x1b")
Q = key(pygame.K_q, "q")


def step(app, *events) -> None:
    app.step(1 / 60, list(events))


def until(app, cond, timeout: float = 5.0) -> bool:
    """조건이 될 때까지 step 을 돌린다 (스레드 결과를 기다릴 때만)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        step(app)
        if cond():
            return True
        time.sleep(0.01)
    return False


def name(app) -> str:
    return type(app.scene).__name__


def _save_device(tmp_path, url: str) -> None:
    DeviceStore(tmp_path / "data" / "device.json").save(Device(url, "tok", KEY, 1, "테스트 행사"))


def _activate(tmp_path, make_bundle, version: int, title: str) -> None:
    store = BundleStore(tmp_path / "data")
    raw, assets = make_bundle(version=version, settings_patch={"branding": {"title": title}})
    store.stage(raw, assets.__getitem__)
    store.activate(version)


@pytest.fixture
def paired(tmp_path, fake_server):
    _save_device(tmp_path, fake_server.url)


@pytest.fixture
def paired_with_bundle(tmp_path, fake_server, make_bundle):
    _save_device(tmp_path, fake_server.url)
    _activate(tmp_path, make_bundle, 1, "가을 축제")


@pytest.fixture
def srv(fake_server):
    """페어링을 받아 주는 가짜 서버 (번들은 아직 게시 전)."""
    fake_server.route("POST", "/api/booth/pair", lambda r: (200, {}, {
        "device_token": "t" * 43, "bundle_key": base64.urlsafe_b64encode(KEY).decode(),
        "event": {"id": 1, "name": "테스트 행사"}}))
    fake_server.route("GET", "/api/booth/bundle", lambda r: (404, {}, {"error": "not_published"}))
    fake_server.route("POST", "/api/booth/heartbeat", lambda r: (204, {}, None))
    return fake_server


class Busy(Scene):
    """촬영 중 같은 장면 (번들 교체 금지)."""


class Boom(Scene):
    def update(self, dt):
        raise RuntimeError("장면 오류 테스트")


# ---- 시작 장면 ----

def test_unpaired_starts_at_pairing(make_app):
    app = make_app()
    assert name(app) == "PairingScene"
    assert app.scene.remote_state() == "N|0|8"


def test_empty_server_url_shows_env_hint(make_app):
    app = make_app({"SERVER_URL": ""})
    assert name(app) == "PairingScene"
    assert "SERVER_URL" in app.scene.message
    step(app, *digits("12345678"), ENTER)  # 입력해도 요청하지 않는다
    assert app.device is None


def test_paired_with_bundle_starts_idle_offline(make_app, paired_with_bundle, tmp_path, fake_server):
    fake_server.close()  # 서버 꺼짐
    app = make_app()
    step(app)
    assert name(app) == "IdleScene"
    assert app.bundle.version == 1 and app.theme.title == "가을 축제"
    assert app.scene.remote_state() == "I|가을 축제"
    assert app.pin_gate is not None


def test_paired_without_bundle_waits(make_app, paired):
    app = make_app()
    step(app)
    assert name(app) == "WaitingScene"
    assert app.scene.idle and app.scene.remote_state() == "W"


# ---- 페어링 ----

def test_digit_dial_keys():
    got = []
    d = DigitDial(4)
    d.on_submit = got.append
    d.handle(key(pygame.K_UP))          # 빈 자리 ↑ → 0
    d.handle(key(pygame.K_UP))          # → 1
    d.handle(key(pygame.K_RIGHT))
    d.handle(key(pygame.K_DOWN))        # 빈 자리 ↓ → 9
    assert d.entered() == 2
    d.handle(ENTER)                     # 다 차지 않으면 제출하지 않고 다음 빈 자리로
    assert got == [] and d.cursor == 2
    for e in digits("57"):              # 숫자 키는 넣고 오른쪽으로 (마지막 자리에선 그대로)
        d.handle(e)
    d.handle(key(pygame.K_BACKSPACE, "\b"))  # 마지막 자리 지우기
    assert d.entered() == 3
    d.handle(key(pygame.K_KP3, "3"))
    d.handle(ENTER)
    assert got == ["1953"]
    assert d.entered() == 4


def test_pairing_via_dial_keys(make_app, srv, tmp_path):
    app = make_app()
    step(app, *digits("12345678"), ENTER)
    assert until(app, lambda: name(app) == "WaitingScene")
    assert (tmp_path / "data" / "device.json").is_file()
    assert app.device.event_id == 1 and app.sync is not None
    pair_req = [r for r in srv.requests if r.path == "/api/booth/pair"]
    assert b'"12345678"' in pair_req[0].body
    assert until(app, lambda: app.sync.not_published)  # 동기화도 시작됐다


def test_pairing_bad_code_message(make_app, fake_server):
    fake_server.route("POST", "/api/booth/pair", lambda r: (400, {}, {"error": "invalid_code"}))
    app = make_app()
    step(app, *digits("12345678"), ENTER)
    assert until(app, lambda: "맞지 않" in app.scene.message)
    assert name(app) == "PairingScene" and app.device is None


# ---- 번들 교체 ----

def test_bundle_swap_only_when_idle(make_app, paired_with_bundle, make_bundle):
    app = make_app()
    raw, assets = make_bundle(version=2, settings_patch={"branding": {"title": "겨울 축제"}})
    app.store.stage(raw, assets.__getitem__)
    app.go(Busy(app))
    app.sync.ready_version = 2
    step(app)
    step(app)
    assert isinstance(app.scene, Busy) and app.bundle.version == 1  # 촬영 중엔 보류
    app.home()
    step(app)
    assert app.bundle.version == 2 and app.theme.title == "겨울 축제"
    assert name(app) == "IdleScene"
    assert app.store.current().version == 2


# ---- 연결 해제 ----

def test_revoked_goes_to_pairing_and_orphans(make_app, paired_with_bundle, fake_server, tmp_path):
    revoked = lambda r: (401, {}, {"error": "device_revoked"})  # noqa: E731
    for m, p in (("GET", "/api/booth/bundle"), ("POST", "/api/booth/heartbeat"), ("POST", "/api/booth/photos")):
        fake_server.route(m, p, revoked)
    outbox = tmp_path / "data" / "outbox"
    outbox.mkdir(parents=True)
    (outbox / "abcdefghijklmnop.jpg").write_bytes(b"jpeg")
    app = make_app()
    assert until(app, lambda: name(app) == "PairingScene")
    assert "연결이 해제" in app.scene.message
    assert not (tmp_path / "data" / "device.json").exists()
    assert app.device is None and app.bundle is None and app.sync is None
    assert app.store.current() is None
    assert (outbox / "orphaned" / "abcdefghijklmnop.jpg").is_file()


# ---- 장면 오류 ----

def test_scene_exception_returns_home(make_app, paired_with_bundle):
    app = make_app()
    app.go(Boom(app))
    step(app)
    assert name(app) == "IdleScene"


def test_global_keys_f2_f5(make_app, paired_with_bundle):
    app = make_app()
    skipped = []
    busy = Busy(app)
    busy.skip = lambda: skipped.append(1)
    app.go(busy)
    step(app, key(pygame.K_F2))
    assert skipped == [1]
    step(app, key(pygame.K_F5))
    assert name(app) == "IdleScene"


# ---- 관리자 패널 ----

def test_admin_requires_pin_then_shows_panel(make_app, paired_with_bundle):
    app = make_app()
    shots = []
    app.start_shoot = lambda: shots.append(1)
    step(app, ENTER)
    assert shots == [1]  # 대기 화면 Enter → 촬영 시작

    step(app, ESC)
    assert app.admin is not None and app.admin.mode == "pin"
    assert app.admin.remote_state() == "N|0|6"
    step(app, ENTER)  # PIN 입력 중 Enter 는 장면으로 가지 않는다
    step(app, *digits("482916"), ENTER)
    assert app.admin.mode == "panel"
    step(app, ENTER, key(pygame.K_SPACE, " "))
    assert shots == [1]  # 패널이 열려 있으면 장면 입력 차단
    step(app, ESC)
    assert app.admin is None

    step(app, ESC)  # 다시 열면 PIN 부터
    assert app.admin.mode == "pin"
    for _ in range(5):
        step(app, *digits("000000"), ENTER)
    assert app.admin.mode == "pin" and "초" in app.admin.message
    step(app, *digits("482916"), ENTER)  # 잠긴 동안엔 맞는 PIN 도 거절
    assert app.admin.mode == "pin"


def test_q_twice_quits(make_app, paired_with_bundle):
    app = make_app()
    step(app, ESC, *digits("482916"), ENTER)
    assert app.admin.mode == "panel"
    step(app, Q)
    assert app.running
    step(app, Q)
    assert not app.running


def test_q_in_pin_mode_does_not_quit(make_app, paired_with_bundle):
    app = make_app()
    step(app, ESC, Q, Q)
    assert app.running


def test_unpaired_esc_quit_only(make_app):
    app = make_app()
    step(app, ESC)
    assert app.admin.mode == "quit_only"
    step(app, *digits("1"))  # 다이얼로 가지 않는다
    assert app.scene.dial.entered() == 0
    step(app, Q, Q)
    assert not app.running


def test_paired_without_bundle_limited_panel(make_app, paired):
    app = make_app()
    step(app, ESC)
    assert app.admin.mode == "limited"
    assert app.admin.buttons() == ["import"]


def test_admin_unpair_needs_confirm(make_app, paired_with_bundle, tmp_path):
    app = make_app()
    step(app, ESC, *digits("482916"), ENTER)
    right = key(pygame.K_RIGHT)
    step(app, right, right, ENTER)
    assert app.device is not None  # 한 번 더 눌러야 한다
    step(app, ENTER)
    assert name(app) == "PairingScene" and app.admin is None
    assert not (tmp_path / "data" / "device.json").exists()


# ---- 비상용 zip ----

def _zip(path, raw: bytes, assets: dict, key: bytes = KEY) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("bundle.json", raw)
        for sha, data in assets.items():
            z.writestr(f"assets/{sha}", data)
        z.writestr("signature", hmac.new(key, raw, "sha256").hexdigest())
    path.write_bytes(buf.getvalue())


def test_import_zip_from_admin_applies(make_app, paired_with_bundle, make_bundle, tmp_path):
    imp = tmp_path / "data" / "import"
    imp.mkdir(parents=True)
    raw, assets = make_bundle(version=3, settings_patch={"branding": {"title": "비상 번들"}})
    _zip(imp / "good.zip", raw, assets)
    app = make_app()
    app.import_dirs = lambda: [imp]
    step(app, ESC, *digits("482916"), ENTER, key(pygame.K_RIGHT), ENTER)
    assert name(app) == "ImportZipScene" and app.admin is None
    assert [p.name for p in app.scene.files] == ["good.zip"]
    step(app, ENTER)
    assert app.bundle.version == 3 and app.theme.title == "비상 번들"
    assert "적용" in app.scene.message
    step(app, ENTER)
    assert name(app) == "IdleScene"


def test_import_zip_bad_signature_message(make_app, paired_with_bundle, make_bundle, tmp_path):
    imp = tmp_path / "data" / "import"
    imp.mkdir(parents=True)
    raw, assets = make_bundle(version=3)
    _zip(imp / "bad.zip", raw, assets, key=b"x" * 32)
    app = make_app()
    app.import_dirs = lambda: [imp]
    from walnut.scenes.import_zip import ImportZipScene
    app.go(ImportZipScene(app))
    step(app, ENTER)
    assert "서명" in app.scene.message and app.bundle.version == 1


# ---- 재페어링 · 다른 행사 번들 · 정리 실패 ----

def test_pairing_orphans_leftover_outbox(make_app, srv, tmp_path):
    """device.json 이 없어진 채 outbox 에 남은 사진은 새 행사로 올라가지 않는다."""
    outbox = tmp_path / "data" / "outbox"
    outbox.mkdir(parents=True)
    (outbox / "abcdefghijklmnop.jpg").write_bytes(b"jpeg")
    srv.route("POST", "/api/booth/photos", lambda r: (201, {}, {}))
    app = make_app()
    step(app, *digits("12345678"), ENTER)
    assert until(app, lambda: name(app) == "WaitingScene")
    assert (outbox / "orphaned" / "abcdefghijklmnop.jpg").is_file()
    assert not [r for r in srv.requests if r.path == "/api/booth/photos"]


def test_other_event_current_bundle_ignored_at_start(make_app, paired, make_bundle, tmp_path):
    store = BundleStore(tmp_path / "data")
    raw, assets = make_bundle(version=1, event_id=99)
    store.stage(raw, assets.__getitem__)
    store.activate(1)
    app = make_app()
    assert app.bundle is None and name(app) == "WaitingScene"
    assert app.store.current() is None  # 버려서 다음 동기화가 새로 받는다


def test_other_event_ready_bundle_discarded(make_app, paired_with_bundle, make_bundle):
    app = make_app()
    raw, assets = make_bundle(version=2, event_id=99)
    app.store.stage(raw, assets.__getitem__)
    app.sync.ready_version = 2
    step(app)
    assert app.bundle.version == 1 and app.sync.ready_version is None
    assert app.store.peek(2) is None and app.store.current().version == 1


def test_swap_succeeds_when_old_asset_cannot_be_deleted(make_app, paired_with_bundle, make_bundle, monkeypatch):
    from pathlib import Path

    app = make_app()
    real_unlink = Path.unlink

    def locked(self, *a, **kw):
        if self.parent.name == "assets":
            raise PermissionError(32, "다른 프로세스가 파일을 사용 중")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(Path, "unlink", locked)
    for v in (2, 3):
        raw, assets = _own_frame_bundle(make_bundle, v, {"branding": {"title": f"v{v}"}})
        app.store.stage(raw, assets.__getitem__)
        app.sync.ready_version = v
        step(app)
        assert app.bundle.version == v and app.theme.title == f"v{v}"
    assert app.store.current().version == 3


def _own_frame_bundle(make_bundle, v: int, settings_patch: dict | None = None):
    """버전마다 다른 프레임 PNG 를 쓰는 번들 (에셋을 서로 공유하지 않게)."""
    buf = io.BytesIO()
    Image.new("RGBA", (400, 600), (v * 40 % 256, 200, 210, 255)).save(buf, "PNG")
    sha = hashlib.sha256(buf.getvalue()).hexdigest()
    frame = {**json.loads(make_bundle()[0])["frames"][0], "asset": sha}
    raw, _ = make_bundle(version=v, frames=[frame], settings_patch=settings_patch)
    return raw, {sha: buf.getvalue()}


def test_event_font_asset_pruned_after_swaps(make_app, paired, make_bundle, tmp_path):
    """행사 글꼴을 쓰던 번들에서 글꼴 없는 번들로 바뀐 뒤, 옛 글꼴 파일이 열린 채로 남아 지우지 못하는 일이 없다."""
    from walnut import fonts

    font = (fonts._D / "Paperlogy-5Medium.ttf").read_bytes()
    font_sha = hashlib.sha256(font).hexdigest()
    store = BundleStore(tmp_path / "data")
    raw, assets = make_bundle(version=1, settings_patch={"branding": {"font_asset": font_sha, "title": "글꼴"}})
    store.stage(raw, {**assets, font_sha: font}.__getitem__)
    store.activate(1)
    app = make_app()
    assert app.theme.font_path is not None
    step(app)  # 그리면서 행사 글꼴을 연다
    for v in (2, 3):
        raw, assets = _own_frame_bundle(make_bundle, v)
        app.store.stage(raw, assets.__getitem__)
        app.sync.ready_version = v
        step(app)
        assert app.bundle.version == v
    assert not app.store.has_asset(font_sha)  # v1 이 정리되며 글꼴도 지워졌다


def test_shutdown_does_not_wait_for_slow_sync(make_app, paired_with_bundle, fake_server):
    """동기화 요청이 오래 걸려도 종료가 창을 붙잡고 기다리지 않는다."""
    got = []

    def slow(req):
        got.append(1)
        time.sleep(4)
        return 404, {}, {"error": "not_published"}

    fake_server.route("GET", "/api/booth/bundle", slow)
    app = make_app()
    end = time.monotonic() + 5
    while not got and time.monotonic() < end:
        time.sleep(0.01)
    assert got
    t = time.monotonic()
    app.shutdown()
    assert time.monotonic() - t < 2.5
    assert not pygame.display.get_init()
