"""디자인 기준 스크린샷 — 지금 Python 부스의 화면 14장을 PNG 로 남긴다.

평소에는 건너뛴다. BASELINE_OUT 에 폴더를 주면 그 폴더에 저장한다.
    BASELINE_OUT=../docs/design/booth-baseline .venv/bin/python -m pytest tests/test_design_baseline.py -q
화면비는 BASELINE_RATIO (16x9 기본 · 16x10 · 4x3 · 3x4 · 9x16 · 9x19.5) 로 고른다.
시계 · 토큰 · 서버 주소 · 동기화 상태를 고정해서 두 번 찍으면 바이트까지 같다.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest
from PIL import Image

from walnut.bundle import BundleStore
from walnut.device import Device, DeviceStore
from walnut.scenes import admin as admin_mod
from walnut.scenes import import_zip as import_mod
from walnut.scenes import share as share_mod

pytestmark = pytest.mark.skipif(not os.environ.get("BASELINE_OUT"),
                                reason="기준 스크린샷은 BASELINE_OUT 이 있을 때만")

# BASELINE_RATIO: 화면비 이름 → 그 화면비에서 모니터(창) 크기 (shared/booth-design/stage_fixtures.json 의 win)
RATIO_WIN = {"16x9": (1920, 1080), "16x10": (1920, 1200), "4x3": (1600, 1200), "3x4": (1200, 1600),
             "9x16": (1080, 1920), "9x19.5": (1080, 2340)}
RATIO = os.environ.get("BASELINE_RATIO", "16x9")
if RATIO not in RATIO_WIN:
    raise pytest.UsageError(f"BASELINE_RATIO 는 {' · '.join(RATIO_WIN)} 중 하나여야 합니다 (지금 {RATIO})")

KEY = b"k" * 32
DT = 0.25
TOKEN = "BASELINEtoken0000000"
SERVER = "https://fourcutbooth.team-cluster.kr"
ALL_FILTERS = ["original", "mono", "warm", "cool", "fade", "vintage"]

EXPECTED_NAMES = sorted(f"{n}.png" for n in [
    "01-pairing", "02-dial", "03-idle", "04-choose-filter", "05-choose-frame", "06-capture", "07-pick",
    "08-review", "09-retake", "10-share", "11-print-copies", "12-admin", "12b-import", "13-waiting",
])


def key(k: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode="", mod=0, scancode=0)


ENTER, LEFT, RIGHT, UP, DOWN, ESC = (key(k) for k in (pygame.K_RETURN, pygame.K_LEFT, pygame.K_RIGHT,
                                                      pygame.K_UP, pygame.K_DOWN, pygame.K_ESCAPE))


def step(app, *events, dt: float = 1 / 60) -> None:
    app.step(dt, list(events))


def run(app, secs: float, dt: float = DT) -> None:
    for _ in range(int(round(secs / dt))):
        app.step(dt, [])


def name(app) -> str:
    return type(app.scene).__name__


def shot(app, path: Path) -> None:
    """그리기가 끝난 프레임을 저장한다. dt=0 이라 시간은 흐르지 않는다."""
    for _ in range(3):
        app.step(0.0, [])
    pygame.image.save(app.screen, str(path))


def fixed_sync(**kw) -> SimpleNamespace:
    """진짜 동기화 스레드 대신 고정된 상태 (네트워크 타이밍이 화면에 섞이지 않게)."""
    base = dict(ready_version=None, not_published=False, online=True, last_error="", last_ok_at=988.0,
                sync_now=lambda: None, stop=lambda timeout=None: None)
    base.update(kw)
    return SimpleNamespace(**base)


def freeze(app, **sync_kw) -> None:
    app._stop_sync()
    app.sync = fixed_sync(**sync_kw)
    app.fps = 60.0


@pytest.fixture
def ratio_name() -> str:
    """이 시험이 쓰는 화면비 (화면비 검사는 parametrize 로 바꿔 끼운다)."""
    return RATIO


@pytest.fixture
def baseline_env(make_app, make_bundle, tmp_path, fake_server, monkeypatch, ratio_name):
    """(fresh_app, bundle_app) — 앱을 하나씩 새로 만든다 (데이터 폴더를 비우고 이전 앱을 닫는다)."""
    fake_server.route("POST", "/api/booth/photos", lambda r: (503, {"Retry-After": "30"}, {"error": "retry_later"}))
    monkeypatch.setattr(share_mod, "new_token", lambda: TOKEN)
    monkeypatch.setattr(admin_mod, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    current = []

    def reset() -> None:
        if current:
            current.pop().shutdown()
        shutil.rmtree(tmp_path / "data", ignore_errors=True)

    def unpaired():
        reset()
        app = make_app(display_size=RATIO_WIN[ratio_name])
        current.append(app)
        app.scene.server_url = SERVER  # 임시 서버 포트가 화면에 나오지 않게
        return app

    def paired(patch: dict | None = None, bundle: bool = True, two_frames: bool = False):
        reset()
        DeviceStore(tmp_path / "data" / "device.json").save(Device(fake_server.url, "tok", KEY, 1, "테스트 행사"))
        if bundle:
            store = BundleStore(tmp_path / "data")
            raw, assets = make_bundle(version=1, settings_patch=patch)
            if two_frames:
                first = json.loads(raw)["frames"][0]
                second = {**first, "id": 2, "name": "두 컷", "slots": first["slots"][:2]}
                raw, _ = make_bundle(version=1, settings_patch=patch, frames=[first, second])
            store.stage(raw, assets.__getitem__)
            store.activate(1)
        app = make_app(display_size=RATIO_WIN[ratio_name])
        current.append(app)
        step(app)
        return app

    yield SimpleNamespace(unpaired=unpaired, paired=paired)
    reset()


def walk_screens(baseline_env, monkeypatch):
    """화면 14장을 차례로 만들어 (파일 이름 줄기, 앱) 을 내준다. 받은 쪽은 그 자리에서 찍거나 검사한다.

    다음 화면으로 넘어가면 앞 앱은 닫히므로 내준 앱은 그 순간에만 쓴다.
    """
    base = {"capture": {"countdown_sec": 3, "between_sec": 0}, "filters": {"enabled": ALL_FILTERS}}

    # 01 페어링: 코드 3자리를 넣은 상태
    app = baseline_env.unpaired()
    assert name(app) == "PairingScene"
    step(app, *[key(k) for k in (pygame.K_4, pygame.K_8, pygame.K_2)])
    yield "01-pairing", app

    # 13 준비 중: 페어링만 되고 번들 없음
    app = baseline_env.paired(bundle=False)
    assert name(app) == "WaitingScene"
    freeze(app, not_published=True)
    yield "13-waiting", app

    # 03 ~ 06, 08 ~ 10: 필터 6개 · 프레임 2개
    app = baseline_env.paired(base, two_frames=True)
    assert name(app) == "IdleScene"
    yield "03-idle", app
    step(app, ENTER)
    assert name(app) == "ChooseScene" and app.scene.kind == "F"
    step(app, RIGHT)
    yield "04-choose-filter", app
    step(app, ENTER)
    assert name(app) == "ChooseScene" and app.scene.kind == "R"
    yield "05-choose-frame", app
    step(app, ENTER)
    assert name(app) == "CaptureScene" and app.scene.shoot.session.n == 4
    run(app, 3 + DT)          # 첫 컷 촬영
    run(app, 1.0)             # 둘째 컷 카운트다운 — 화면에는 큰 숫자 2
    assert app.scene.state == "countdown" and app.scene.remote_state().startswith("C|1|4|18|")
    yield "06-capture", app
    run(app, 2.75 + 2 * 3)    # 남은 컷을 마저 찍는다
    assert name(app) == "ReviewScene"
    yield "08-review", app
    step(app, RIGHT, ENTER)
    assert name(app) == "RetakeScene"
    step(app, ENTER)          # 컷 1번만 '다시 찍기'
    assert app.scene.remote_state().startswith("P|0111|")
    yield "09-retake", app
    step(app, key(pygame.K_F5))  # 처음으로 → 다시 한 판 (공유 화면까지)
    step(app, ENTER, ENTER, ENTER)
    assert name(app) == "CaptureScene"
    run(app, 4 * 3 + DT)
    assert name(app) == "ReviewScene"
    app.device = replace(app.device, server_url=SERVER)  # 화면용으로만 Device.server_url 도 바꾼다 (QR 주소에 임시 서버 포트가 들어가지 않게)
    step(app, ENTER)
    assert name(app) == "ShareScene" and app.scene.url == f"{SERVER}/p/{TOKEN}"
    yield "10-share", app

    # 07 사진 고르기: 여분 2컷 → 6장 중 2장 고른 상태
    app = baseline_env.paired({**base, "capture": {"countdown_sec": 3, "between_sec": 0, "extra_shots": 2},
                               "filters": {"enabled": ["original"]}})
    step(app, ENTER)
    run(app, 6 * 3 + DT)
    assert name(app) == "PickScene"
    colors = [(235, 120, 110), (240, 190, 100), (140, 200, 130), (110, 170, 220), (170, 140, 210), (230, 150, 190)]
    app.scene.shoot.session.shots = [Image.new("RGB", (640, 480), c) for c in colors]
    app.scene.enter()
    step(app, ENTER, RIGHT, RIGHT, ENTER)
    assert app.scene.remote_state().startswith("G|0,-,1,")
    yield "07-pick", app

    # 11 인쇄 매수
    app = baseline_env.paired({"capture": base["capture"], "filters": {"enabled": ["original"]},
                               "print": {"enabled": True, "copies_max": 2}})
    step(app, ENTER)
    run(app, 4 * 3 + DT)
    step(app, ENTER, ENTER)
    assert name(app) == "PrintCopiesScene"
    yield "11-print-copies", app

    # 02 PIN 다이얼 · 12 관리자 패널 · 12b 번들 가져오기
    app = baseline_env.paired(base)
    freeze(app)
    step(app, ESC)
    assert app.admin is not None and app.admin.mode == "pin"
    step(app, key(pygame.K_4), key(pygame.K_8), key(pygame.K_2))
    yield "02-dial", app
    step(app, key(pygame.K_9), key(pygame.K_1), key(pygame.K_6))
    step(app, ENTER)
    assert app.admin.mode == "panel"
    yield "12-admin", app
    monkeypatch.setattr(import_mod, "find_zips", lambda dirs: [
        Path("walnutstudio/data/import/호두네사진관_행사1_v3.zip"),
        Path("/Users/walnut/Downloads/호두네사진관_행사1_v2.zip"),
        Path("/Volumes/USB/호두네사진관_행사1_v1.zip"),
    ])
    step(app, DOWN, ENTER)
    assert name(app) == "ImportZipScene"
    yield "12b-import", app



def test_baseline_screens(baseline_env, monkeypatch):
    out = Path(os.environ["BASELINE_OUT"])
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):  # README 같은 다른 파일은 지우지 않는다
        old.unlink()
    for stem, app in walk_screens(baseline_env, monkeypatch):
        shot(app, out / f"{stem}.png")
        size = app.screen.get_size()
    assert sorted(p.name for p in out.glob("*.png")) == EXPECTED_NAMES
    for p in out.glob("*.png"):
        with Image.open(p) as im:
            assert im.size == size, p.name
