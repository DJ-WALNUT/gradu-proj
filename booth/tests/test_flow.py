"""촬영 흐름: 필터 → [스티커] → 프레임 → 촬영 → (고르기) → 확인/재촬영 → 공유 → [인쇄 매수] → 대기."""

from __future__ import annotations

import json
import re

import pygame
import pytest
from PIL import Image

from walnut.bundle import BundleStore
from walnut.device import Device, DeviceStore
from walnut.stickers import Sticker

KEY = b"k" * 32
DT = 0.25


def key(k: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=k, unicode="", mod=0, scancode=0)


ENTER, LEFT, RIGHT, UP, DOWN = (key(k) for k in (pygame.K_RETURN, pygame.K_LEFT, pygame.K_RIGHT,
                                                  pygame.K_UP, pygame.K_DOWN))


def step(app, *events, dt: float = 1 / 60) -> None:
    app.step(dt, list(events))


def run(app, secs: float, dt: float = DT) -> None:
    """가짜 시간을 secs 만큼 진행한다."""
    for _ in range(int(round(secs / dt))):
        app.step(dt, [])


def name(app) -> str:
    return type(app.scene).__name__


FAST = {"capture": {"countdown_sec": 3, "between_sec": 0}}
ONE_FILTER = {"filters": {"enabled": ["original"]}}


def patch(*parts: dict) -> dict:
    out: dict = {}
    for p in parts:
        for k, v in p.items():
            out.setdefault(k, {}).update(v)
    return out


@pytest.fixture
def app_with_bundle(make_app, make_bundle, tmp_path, fake_server):
    """app_with_bundle(settings_patch) → 페어링 + 번들 v1 이 적용된 App (대기 화면)."""
    # 업로드는 계속 '나중에 다시' → 사진이 outbox 에 남는다
    fake_server.route("POST", "/api/booth/photos", lambda r: (503, {"Retry-After": "30"}, {"error": "retry_later"}))

    def _make(settings_patch: dict | None = None, env: dict | None = None, two_frames: bool = False):
        DeviceStore(tmp_path / "data" / "device.json").save(Device(fake_server.url, "tok", KEY, 1, "테스트 행사"))
        store = BundleStore(tmp_path / "data")
        raw, assets = make_bundle(version=1, settings_patch=settings_patch)
        if two_frames:  # 같은 PNG 에 슬롯 2개(컷 2개)만 쓰는 둘째 프레임
            first = json.loads(raw)["frames"][0]
            second = {**first, "id": 2, "name": "두 컷", "slots": first["slots"][:2]}
            raw, _ = make_bundle(version=1, settings_patch=settings_patch, frames=[first, second])
        store.stage(raw, assets.__getitem__)
        store.activate(1)
        app = make_app(env)
        step(app)
        assert name(app) == "IdleScene"
        return app

    return _make


def shoot_to_review(app, cuts: int = 4, countdown: float = 3) -> None:
    run(app, cuts * countdown + DT)
    assert name(app) == "ReviewScene"


def collages(tmp_path) -> list:
    return sorted((tmp_path / "data" / "collage").glob("*.jpg"))


# ---- 단계 건너뛰기 ----

def test_single_choice_steps_skipped(app_with_bundle):
    app = app_with_bundle(patch(FAST, {"filters": {"enabled": ["mono"]}}))
    step(app, ENTER)  # 필터 1개 · 스티커 꺼짐 · 프레임 1개 → 바로 촬영
    assert name(app) == "CaptureScene"
    s = app.scene.shoot.session
    assert s.filter == "mono" and s.sticker is None and s.n == 4
    assert app.scene.remote_state() == "C|0|4|30|30"


def test_sticker_step_when_detector_available(app_with_bundle):
    app = app_with_bundle(patch(FAST, ONE_FILTER))
    st = Sticker("st_1", "토끼 귀", Image.new("RGBA", (40, 20), (255, 0, 0, 255)), "forehead", 1.0, (0.0, -0.4))
    app.stickers = [st]
    app.detector.available = False
    step(app, ENTER)
    assert name(app) == "CaptureScene"  # 얼굴 인식을 쓸 수 없으면 스티커 단계 없음

    app.home()
    app.detector.available = True
    app.detector.faces = lambda rgb: []  # mediapipe 없이
    step(app, ENTER)
    assert name(app) == "ChooseScene" and app.scene.remote_state() == "L|K|0|2|없음"
    step(app, RIGHT)
    assert app.scene.remote_state() == "L|K|1|2|토끼 귀"
    step(app, ENTER)
    assert name(app) == "CaptureScene"
    assert app.scene.shoot.session.sticker == "st_1" and app.scene.shoot.sticker is st
    run(app, 3 + DT)
    assert len(app.scene.shoot.session.shots) == 1


def test_frame_choice_when_two_frames(app_with_bundle):
    app = app_with_bundle(patch(FAST, ONE_FILTER), two_frames=True)
    step(app, ENTER)
    assert name(app) == "ChooseScene" and app.scene.remote_state() == "L|R|0|2|기본 프레임"
    step(app, RIGHT)
    assert app.scene.remote_state() == "L|R|1|2|두 컷"
    step(app, ENTER)
    assert name(app) == "CaptureScene"
    assert app.scene.shoot.session.n == 2 and app.scene.remote_state() == "C|0|2|30|30"
    run(app, 2 * 3 + DT)
    assert name(app) == "ReviewScene" and app.scene.collage.size == (400, 600)


# ---- 전체 흐름 ----

def test_full_flow_four_cuts_to_share_and_outbox(app_with_bundle, tmp_path):
    app = app_with_bundle(FAST)
    step(app, ENTER)
    assert name(app) == "ChooseScene" and app.scene.kind == "F"
    step(app, RIGHT, ENTER)
    assert name(app) == "CaptureScene" and app.scene.shoot.session.filter == "mono"
    shoot_to_review(app)
    assert app.scene.collage.size == (400, 600)
    step(app, ENTER)
    assert name(app) == "ShareScene"
    files = collages(tmp_path)
    assert len(files) == 1
    token = app.scene.token
    assert re.fullmatch(rf"1_\d{{4}}-\d{{6}}_{re.escape(token)}\.jpg", files[0].name)
    assert len(token) == 16
    assert app.scene.url == f"{app.cfg.server_url}/p/{token}"
    outbox = list((tmp_path / "data" / "outbox").glob("*.jpg"))
    assert [p.name for p in outbox] == [f"{token}.jpg"]
    with Image.open(files[0]) as im:
        assert im.size == (400, 600)
        r, g, b = im.getpixel((100, 160))
        assert abs(r - g) < 6 and abs(g - b) < 6  # mono 필터가 컷에 들어갔다
    step(app, ENTER)  # 인쇄 꺼짐 → 대기
    assert name(app) == "IdleScene"


@pytest.mark.parametrize("mirror", [True, False])
def test_mirror_setting_applies_to_saved_cut(app_with_bundle, mirror):
    app = app_with_bundle(patch(FAST, ONE_FILTER, {"capture": {"mirror": mirror}}))
    raw = app.camera._frame
    raw[:, :10] = (255, 0, 0)  # 카메라 원본 왼쪽 가장자리 빨강
    step(app, ENTER)
    run(app, 3 + DT)
    cut = app.scene.shoot.session.shots[0]
    assert cut.size == (raw.shape[1], raw.shape[0])
    x = cut.width - 1 if mirror else 0  # 거울이면 오른쪽으로 간다
    assert cut.getpixel((x, 0)) == (255, 0, 0)


def test_extra_shots_pick_order(app_with_bundle):
    app = app_with_bundle(patch(FAST, ONE_FILTER, {"capture": {"extra_shots": 2}}))
    step(app, ENTER)
    assert app.scene.remote_state() == "C|0|6|30|30"
    run(app, 6 * 3 + DT)
    assert name(app) == "PickScene"
    s = app.scene.shoot.session
    colors = [(250, 0, 0), (0, 250, 0), (0, 0, 250), (250, 250, 0), (0, 250, 250), (250, 0, 250)]
    s.shots = [Image.new("RGB", (640, 480), c) for c in colors]
    app.scene.enter()  # 썸네일 다시 만들기
    assert app.scene.remote_state() == "G|-,-,-,-,-,-|0|4"
    step(app, *[RIGHT] * 5, ENTER)          # 6번째
    step(app, *[LEFT] * 5, ENTER)           # 1번째
    step(app, *[RIGHT] * 3, ENTER)          # 4번째
    assert app.scene.remote_state() == "G|1,-,-,2,-,0|3|4"
    step(app, ENTER)                         # 다시 누르면 빠진다
    assert app.scene.remote_state() == "G|1,-,-,-,-,0|3|4"
    step(app, ENTER, LEFT, ENTER)            # 4번째 다시, 3번째
    assert s.picks_complete()
    assert app.scene.remote_state() == "G|1,-,3,2,-,0|6|4"  # 다 고르면 [완료] 로
    step(app, ENTER)
    assert name(app) == "ReviewScene"
    col = app.scene.collage
    want = [colors[5], colors[0], colors[3], colors[2]]
    for (x, y), c in zip([(100, 160), (300, 160), (100, 440), (300, 440)], want):
        got = col.getpixel((x, y))
        assert all(abs(a - b) < 8 for a, b in zip(got, c)), (got, c)
    assert app.scene.buttons == ["qr"]  # 고르기 모드엔 다시 찍기 없음


def test_pick_done_disabled_until_complete(app_with_bundle):
    app = app_with_bundle(patch(FAST, ONE_FILTER, {"capture": {"extra_shots": 1}}))
    step(app, ENTER)
    run(app, 5 * 3 + DT)
    assert name(app) == "PickScene"
    step(app, DOWN, ENTER)
    assert name(app) == "PickScene"  # 덜 골랐으면 [완료] 안 됨


# ---- 재촬영 ----

def test_retake_flow_reshoots_only_unkept(app_with_bundle):
    app = app_with_bundle(patch(FAST, ONE_FILTER))
    step(app, ENTER)
    shoot_to_review(app)
    s = app.scene.shoot.session
    before = list(s.shots)
    assert app.scene.buttons == ["qr", "retake"]
    step(app, RIGHT)
    assert app.scene.remote_state().startswith("V|1|")
    step(app, ENTER)
    assert name(app) == "RetakeScene"
    assert app.scene.remote_state() == "P|1111|0|0|0"
    step(app, DOWN, ENTER)  # 다시 찍을 컷이 없으면 [다시 찍기] 안 됨
    assert name(app) == "RetakeScene"
    step(app, UP, RIGHT, ENTER, RIGHT, RIGHT, ENTER)
    assert app.scene.remote_state() == "P|1010|3|0|0"
    step(app, DOWN)
    assert app.scene.remote_state() == "P|1010|3|1|0"
    step(app, ENTER)
    assert name(app) == "CaptureScene"
    assert s.retake_queue == [1, 3]
    assert app.scene.remote_state() == "C|2|4|30|30"
    run(app, 2 * 3 + DT)
    assert name(app) == "ReviewScene"
    assert s.shots[0] is before[0] and s.shots[2] is before[2]
    assert s.shots[1] is not before[1] and s.shots[3] is not before[3]


def test_retake_cancel_returns_to_review(app_with_bundle):
    app = app_with_bundle(patch(FAST, ONE_FILTER))
    step(app, ENTER)
    shoot_to_review(app)
    step(app, RIGHT, ENTER, ENTER, DOWN, RIGHT)
    assert app.scene.remote_state() == "P|0111|0|1|1"
    step(app, ENTER)
    assert name(app) == "ReviewScene"
    assert app.scene.shoot.session.retake_queue == []


def test_allow_retake_false_hides_button(app_with_bundle):
    app = app_with_bundle(patch(FAST, ONE_FILTER, {"capture": {"allow_retake": False}}))
    step(app, ENTER)
    shoot_to_review(app)
    assert app.scene.buttons == ["qr"]
    step(app, RIGHT)
    assert app.scene.remote_state() == f"V|0|{app.scene.left()}|25|1"  # 버튼 1개 — RIGHT 뒤에도 선택 0
    step(app, ENTER)
    assert name(app) == "ShareScene"


def test_review_auto_completes(app_with_bundle):
    app = app_with_bundle(patch(FAST, ONE_FILTER, {"capture": {"review_auto_sec": 10}}))
    step(app, ENTER)
    shoot_to_review(app)
    assert app.scene.remote_state() == "V|0|10|10|2"
    run(app, 6)
    step(app, RIGHT)  # 입력하면 다시 처음부터
    run(app, 6)
    assert name(app) == "ReviewScene"
    run(app, 4.5)
    assert name(app) == "ShareScene"


# ---- 셔터 순간 프레임 없음 ----

def test_shutter_without_frame_retries_same_cut(app_with_bundle):
    app = app_with_bundle(patch(FAST, ONE_FILTER))
    step(app, ENTER)
    run(app, 2.5)
    app.camera.fail = True  # 셔터 직전 케이블 빠짐
    run(app, 1.5)           # 셔터 + 0.5초 기다림 지남
    sc = app.scene
    assert name(app) == "CaptureScene"
    assert len(sc.shoot.session.shots) == 0
    assert sc.state == "camera" and sc.message() == "카메라 연결 중"
    run(app, 5)             # 오래 끊겨도 대기 화면으로 가지 않는다
    assert app.scene is sc and len(sc.shoot.session.shots) == 0
    app.camera.fail = False
    step(app, dt=DT)
    assert sc.state == "countdown" and sc.remote_state() == "C|0|4|30|30"  # 그 컷 카운트다운 처음부터
    run(app, 2.75)
    assert len(sc.shoot.session.shots) == 0
    run(app, 0.5)
    assert len(sc.shoot.session.shots) == 1


def test_short_frame_gap_at_shutter_uses_next_frame(app_with_bundle):
    app = app_with_bundle(patch(FAST, ONE_FILTER))
    step(app, ENTER)
    run(app, 2.75)
    app.camera.fail = True
    run(app, 0.5)  # 셔터 시각 지남, 0.5초 안
    assert len(app.scene.shoot.session.shots) == 0 and app.scene.state == "shutter"
    app.camera.fail = False
    step(app, dt=DT)
    assert len(app.scene.shoot.session.shots) == 1


def test_f2_shutters_immediately(app_with_bundle):
    app = app_with_bundle(patch(FAST, ONE_FILTER))
    step(app, ENTER)
    step(app, key(pygame.K_F2))
    assert len(app.scene.shoot.session.shots) == 1


# ---- 공유 · 인쇄 ----

def test_qr_disabled_shows_saved_message(app_with_bundle, tmp_path):
    app = app_with_bundle(patch(FAST, ONE_FILTER, {"share": {"qr_enabled": False}}))
    step(app, ENTER)
    shoot_to_review(app)
    step(app, ENTER)
    assert name(app) == "ShareScene"
    assert app.scene.url is None and "부스 PC 에 저장되었어요" in app.scene.message()
    assert app.scene.remote_state() == "S|45|45|3"
    assert len(collages(tmp_path)) == 1
    assert list((tmp_path / "data" / "outbox").glob("*.jpg")) == []


def test_no_server_shows_saved_message(app_with_bundle, tmp_path):
    app = app_with_bundle(patch(FAST, ONE_FILTER), env={"SERVER_URL": ""})
    step(app, ENTER)
    shoot_to_review(app)
    step(app, ENTER)
    assert app.scene.url is None and app.scene.remote_state().endswith("|3")


def test_share_timeout_goes_home(app_with_bundle):
    app = app_with_bundle(patch(FAST, ONE_FILTER, {"share": {"qr_screen_sec": 10}}))
    step(app, ENTER)
    shoot_to_review(app)
    step(app, ENTER)
    run(app, 9.5)
    assert name(app) == "ShareScene"
    run(app, 0.75)
    assert name(app) == "IdleScene"


def test_print_copies_spools(app_with_bundle, tmp_path):
    app = app_with_bundle(patch(FAST, ONE_FILTER, {"print": {"enabled": True, "copies_max": 2}}))
    step(app, ENTER)
    shoot_to_review(app)
    step(app, ENTER)
    token = app.scene.token
    step(app, ENTER)
    assert name(app) == "PrintCopiesScene"
    assert app.scene.remote_state() == "Q|1|2"
    step(app, UP, UP)
    assert app.scene.remote_state() == "Q|2|2"  # 최대에서 멈춘다
    step(app, ENTER)
    assert name(app) == "IdleScene"
    spooled = list((tmp_path / "data" / "print_spool").glob("*.png"))
    assert len(spooled) == 1 and spooled[0].name.endswith(f"_{token}_x2.png")


def test_print_copies_timeout_no_print(app_with_bundle, tmp_path):
    app = app_with_bundle(patch(FAST, ONE_FILTER, {"print": {"enabled": True}}))
    step(app, ENTER)
    shoot_to_review(app)
    step(app, ENTER, ENTER)
    assert name(app) == "PrintCopiesScene"
    run(app, 30.25)
    assert name(app) == "IdleScene"
    assert not list((tmp_path / "data" / "print_spool").glob("*.png"))


# ---- 리모컨 ----

def test_remote_lines_through_flow(app_with_bundle):
    app = app_with_bundle({"capture": {"countdown_sec": 3, "between_sec": 2}})
    step(app, ENTER)
    assert app.scene.remote_state() == "L|F|0|6|원본"
    step(app, LEFT)
    assert app.scene.remote_state() == "L|F|5|6|빈티지"
    step(app, RIGHT, RIGHT)
    assert app.scene.remote_state() == "L|F|1|6|흑백"
    step(app, ENTER)
    assert app.scene.remote_state() == "C|0|4|30|30"
    run(app, 1.0)
    assert app.scene.remote_state() == "C|0|4|20|30"
    run(app, 2.0 + DT)
    assert app.scene.remote_state() == "C|1|4|-1|30"  # 다음 포즈 준비
    run(app, 2.0)
    assert app.scene.remote_state().startswith("C|1|4|")
    assert app.scene.state == "countdown"
    run(app, 12.75 + DT)  # 남은 2.75 + (준비 2 + 3) × 2
    assert name(app) == "ReviewScene"
    assert app.scene.remote_state() == "V|0|25|25|2"
    step(app, ENTER)
    line = app.scene.remote_state()
    assert re.fullmatch(r"S\|45\|45\|[0-3]", line), line


def test_bundle_published_mid_shoot_waits(app_with_bundle, make_bundle):
    app = app_with_bundle(patch(FAST, ONE_FILTER))
    raw, assets = make_bundle(version=2, settings_patch={"branding": {"title": "새 번들"}})
    app.store.stage(raw, assets.__getitem__)
    step(app, ENTER)
    app.sync.ready_version = 2
    run(app, 4 * 3 + DT)
    assert name(app) == "ReviewScene" and app.bundle.version == 1
    step(app, ENTER)
    step(app)
    assert name(app) == "ShareScene" and app.bundle.version == 1
    step(app, ENTER)  # 공유 끝 → 대기 화면에서 교체
    step(app)
    assert name(app) == "IdleScene" and app.bundle.version == 2 and app.theme.title == "새 번들"


def test_no_frames_does_not_start(app_with_bundle):
    app = app_with_bundle()
    app.bundle.frames = []
    step(app, ENTER)
    assert name(app) == "IdleScene"


def test_share_qr_uses_device_server_url(app_with_bundle):
    """QR 은 사진을 올리는 곳(device.server_url) 을 가리킨다. SERVER_URL 이 그 뒤 바뀌었어도."""
    import dataclasses

    from walnut.scenes.share import finish

    app = app_with_bundle()
    app.device = dataclasses.replace(app.device, server_url="http://paired.example")
    finish(app, Image.new("RGB", (400, 600), "white"))
    assert name(app) == "ShareScene"
    assert app.scene.url == f"http://paired.example/p/{app.scene.token}"
