"""개발자 모드 (--dev-mode · --dev-mode-all) — 연결 없이 버스트샷을 켠 채 실행."""

from __future__ import annotations

import pytest

import main
from walnut import config, model_files
from walnut.analysis import BurstAnalyzer
from walnut.app import App
from walnut.device import Device, DeviceStore
from walnut.scenes.admin import AdminPanel

ENV = {"BOOTH_FULLSCREEN": "false", "REMOTE_PORT": "off", "BOOTH_MOTION": "false", "PRINTER_PORT": "dummy"}


def _fake_model() -> bytes:
    """진짜 모델처럼 보이는 내용 — 충분히 큰 zip."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("face_detector.tflite", b"0" * model_files.MIN_BYTES)
    return buf.getvalue()


MODEL = _fake_model()
TFLITE = b"\x1c\x00\x00\x00TFL3" + b"0" * model_files.MIN_BYTES   # 사람 찾기 모델처럼 보이는 내용
ALL = ["face_landmarker.task", "efficientdet_lite0.tflite"]


def body_for(dest) -> bytes:
    """받는 중인 파일(.part)이 어느 모델인지 보고 그 모양의 내용."""
    return TFLITE if dest.name.startswith("efficientdet") else MODEL


def fake_download(url, dest):
    dest.write_bytes(body_for(dest))


def test_dev_config(tmp_path):
    base = config.load({"SERVER_URL": "https://x.test"}, root=tmp_path)
    for mode in ("on", "all"):
        c = config.dev_config(base, mode)
        # 개발자 모드는 버스트샷과 구도 보정을 모두 켠다 (.env 에 없어도)
        assert (c.dev, c.burst, c.smart_crop, c.server_url) == (mode, True, True, "")
        assert c.data_dir == tmp_path / "data-dev"
    assert base.dev == "" and base.data_dir == tmp_path / "data"


def test_args():
    assert main.dev_mode(main.parse_args([])) == ""
    assert main.dev_mode(main.parse_args(["--dev-mode", "--windowed"])) == "on"
    assert main.dev_mode(main.parse_args(["--dev-mode-all", "--no-camera"])) == "all"
    with pytest.raises(SystemExit):
        main.parse_args(["--dev-mode", "--dev-mode-all"])


@pytest.fixture
def dev_app(tmp_path, monkeypatch):
    """dev_app(mode) → 개발자 모드 App. 실제 data/ 에는 페어링 정보가 이미 있다."""
    monkeypatch.setattr(BurstAnalyzer, "warm", lambda self: None)  # 모델은 불러오지 않는다
    real = tmp_path / "data"
    DeviceStore(real / "device.json").save(Device("https://x.test", "tok", b"k" * 32, 5, "진짜 행사"))
    apps = []

    def _make(mode: str = "on"):
        cfg = config.dev_config(config.load(ENV, root=tmp_path), mode)
        app = App(cfg, no_camera=True, windowed=True, display_size=(1920, 1080))
        apps.append(app)
        return app

    yield _make
    for a in apps:
        a.shutdown()


def test_dev_app_starts_local_with_burst(dev_app):
    app = dev_app("on")
    assert type(app.scene).__name__ == "IdleScene" and app.local and app.device is None
    assert app.bundle.settings["capture"]["countdown_sec"] == 4
    assert app.analyzer is not None and app.sync is None
    assert "개발자 모드" in app.local_note()


def test_dev_app_leaves_real_data_alone(dev_app, tmp_path):
    real = tmp_path / "data"
    before = (real / "device.json").read_bytes()
    app = dev_app("all")
    app.step(1 / 60, [])
    assert (real / "device.json").read_bytes() == before
    assert sorted(p.name for p in real.iterdir()) == ["device.json"]
    assert (tmp_path / "data-dev" / "assets").is_dir()


def test_dev_app_ignores_device_file_in_dev_folder(dev_app, tmp_path):
    DeviceStore(tmp_path / "data-dev" / "device.json").save(Device("https://x.test", "tok", b"k" * 32, 5, "행사"))
    app = dev_app("on")
    assert app.device is None and app.local


def test_dev_admin_has_no_pair_button(dev_app):
    app = dev_app("on")
    panel = AdminPanel(app)
    assert panel.mode == "local" and panel.buttons() == ["home", "next"]


def test_ensure_downloads_only_missing(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(model_files, "_download", lambda url, dest: (calls.append(url), fake_download(url, dest)))
    assert model_files.ensure(tmp_path / "models") == ALL
    assert model_files.ensure(tmp_path / "models") == [] and len(calls) == 2
    assert (tmp_path / "models" / "face_landmarker.task").read_bytes() == MODEL
    assert (tmp_path / "models" / "efficientdet_lite0.tflite").read_bytes() == TFLITE


def test_ensure_failure_leaves_no_partial(tmp_path, monkeypatch):
    def boom(url, dest):
        dest.write_bytes(b"half")
        raise OSError("offline")

    monkeypatch.setattr(model_files, "_download", boom)
    with pytest.raises(OSError):
        model_files.ensure(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_main_exits_with_message_when_model_missing(monkeypatch, capsys):
    def offline(models_dir, on_start=None):
        raise OSError("offline")

    monkeypatch.setattr(model_files, "ensure", offline)
    monkeypatch.setattr(App, "__init__", lambda *a, **k: pytest.fail("모델 없이 앱을 띄우면 안 된다"))
    with pytest.raises(SystemExit) as exc:
        main.main(["--dev-mode-all", "--no-camera"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "모델을 내려받지 못했습니다" in out and "offline" in out and "download_models.py" in out


def test_main_without_dev_does_not_fetch_models(monkeypatch):
    monkeypatch.setattr(model_files, "ensure", lambda d, on_start=None: pytest.fail("일반 실행은 모델을 받지 않는다"))
    seen = {}

    def fake_init(self, cfg, no_camera=False, windowed=False, display_size=None):
        seen["dev"] = cfg.dev

    monkeypatch.setattr(App, "__init__", fake_init)
    monkeypatch.setattr(App, "run", lambda self, max_frames=None: None)
    main.main(["--no-camera"])
    assert seen == {"dev": ""}


def test_dev_messages_print_on_korean_windows_console(monkeypatch, capsys):
    """한국어 Windows 콘솔(cp949)에 없는 글자를 찍으면 실행이 죽는다."""
    monkeypatch.setattr(model_files, "ensure", lambda d, on_start=None: ["face_landmarker.task"])
    monkeypatch.setattr(App, "__init__", lambda self, cfg, **k: None)
    monkeypatch.setattr(App, "run", lambda self, max_frames=None: None)
    main.main(["--dev-mode"])
    out = capsys.readouterr().out
    assert "개발자 모드" in out and "data-dev" in out
    out.encode("cp949")


# ---- 내려받은 파일이 모델이 아닐 때 (로그인 페이지 · 끊긴 연결) ----

@pytest.mark.parametrize("body", [b"<html>login</html>", b"PK" + b"0" * 100, b"0" * 2_000_000, MODEL[:len(MODEL) // 2], b""],
                         ids=["html", "short", "not_zip", "half", "empty"])
def test_ensure_rejects_a_file_that_is_not_the_model(tmp_path, monkeypatch, body):
    monkeypatch.setattr(model_files, "_download", lambda url, dest: dest.write_bytes(body))
    with pytest.raises(OSError):
        model_files.ensure(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_ensure_replaces_a_broken_existing_file(tmp_path, monkeypatch):
    (tmp_path / "face_landmarker.task").write_bytes(b"<html>login</html>")  # 지난 실행이 남긴 잘못된 파일
    (tmp_path / "efficientdet_lite0.tflite").write_bytes(TFLITE)               # 이쪽은 멀쩡하다 — 다시 받지 않는다
    monkeypatch.setattr(model_files, "_download", fake_download)
    assert model_files.ensure(tmp_path) == ["face_landmarker.task"]
    assert (tmp_path / "face_landmarker.task").read_bytes() == MODEL


def test_ensure_turns_other_download_errors_into_oserror(tmp_path, monkeypatch):
    import http.client

    def boom(url, dest):
        dest.write_bytes(b"half")
        raise http.client.IncompleteRead(b"half")

    monkeypatch.setattr(model_files, "_download", boom)
    with pytest.raises(OSError):
        model_files.ensure(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_ensure_announces_before_downloading(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(model_files, "_download", lambda url, dest: (order.append("download"), fake_download(url, dest)))
    model_files.ensure(tmp_path, on_start=lambda name: order.append(f"start:{name}"))
    assert order == ["start:face_landmarker.task", "download", "start:efficientdet_lite0.tflite", "download"]
    model_files.ensure(tmp_path, on_start=lambda name: order.append("again"))
    assert "again" not in order  # 이미 있으면 알리지 않는다


def test_short_read_is_an_error(tmp_path, monkeypatch):
    """서버가 알려 준 크기보다 덜 받았으면 실패다 (연결이 중간에 끊겨도 read 는 예외 없이 끝난다)."""
    import io

    class Resp(io.BytesIO):
        headers = {"Content-Length": "1000"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(model_files.urllib.request, "urlopen", lambda *a, **k: Resp(b"x" * 10))
    with pytest.raises(OSError):
        model_files._download("https://x.test/m", tmp_path / "m.part")


def test_main_announces_download(monkeypatch, capsys):
    def fake_ensure(models_dir, on_start=None):
        on_start("face_landmarker.task")
        return ["face_landmarker.task"]

    monkeypatch.setattr(model_files, "ensure", fake_ensure)
    monkeypatch.setattr(App, "__init__", lambda self, cfg, **k: None)
    monkeypatch.setattr(App, "run", lambda self, max_frames=None: None)
    main.main(["--dev-mode"])
    out = capsys.readouterr().out
    assert "내려받는 중" in out
    out.encode("cp949")


# ---- 분석기를 쓸 수 없을 때 (모델이 깨졌거나 불러오지 못함) ----

def test_dev_note_says_burst_is_off_when_model_unusable(dev_app):
    app = dev_app("all")
    app.analyzer.available = True
    assert "꺼짐" not in app.local_note()
    app.analyzer.available = False
    assert "버스트샷 꺼짐" in app.local_note() and "개발자 모드" in app.local_note()


def test_dev_all_still_explains_each_cut_when_model_unusable(dev_app):
    import pygame

    app = dev_app("all")
    app.analyzer.available = False
    enter = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN, unicode="", mod=0, scancode=0)
    for _ in range(200):  # 필터 고르기는 Enter 로 넘기고 첫 컷까지
        scene = type(app.scene).__name__
        app.step(0.1, [enter] if scene in ("IdleScene", "ChooseScene") else [])
        if type(app.scene).__name__ == "BurstShowScene":
            break
    assert type(app.scene).__name__ == "BurstShowScene"
    assert app.scene.data.info is None and app.scene.n == 0
    assert len(app.scene.data.frames) == 0 and "분석을 끝내지 못해" in app.scene.reason


# ---- 사람 찾기 모델 (.tflite 는 zip 이 아닐 수도 있어 따로 확인한다) ----

@pytest.mark.parametrize("body,ok", [(TFLITE, True), (b"\x1c\x00\x00\x00TFL3" + b"0" * 100, False),
                                     (MODEL, False), (b"<html>login</html>", False), (b"0" * 2_000_000, False),
                                     (b"", False)],
                         ids=["tflite", "short", "zip_without_mark", "html", "no_mark", "empty"])
def test_model_files_tflite_validation(tmp_path, body, ok):
    p = tmp_path / "efficientdet_lite0.tflite"
    p.write_bytes(body)
    assert model_files.looks_valid(p) is ok
    part = tmp_path / "efficientdet_lite0.part"     # 받는 중인 파일은 이름으로 종류를 알려 준다
    part.write_bytes(body)
    assert model_files.looks_valid(part, "efficientdet_lite0.tflite") is ok


def test_task_model_still_needs_zip(tmp_path):
    p = tmp_path / "face_landmarker.task"
    p.write_bytes(TFLITE)
    assert model_files.looks_valid(p) is False
    p.write_bytes(MODEL)
    assert model_files.looks_valid(p) is True


def test_ensure_rejects_broken_tflite_and_keeps_face_model(tmp_path, monkeypatch):
    def download(url, dest):
        dest.write_bytes(b"<html>login</html>" if dest.name.startswith("efficientdet") else MODEL)

    monkeypatch.setattr(model_files, "_download", download)
    with pytest.raises(OSError, match="efficientdet_lite0.tflite"):
        model_files.ensure(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["face_landmarker.task"]   # 조각은 남기지 않는다


def test_models_list_has_person_model_url():
    url = model_files.MODELS["efficientdet_lite0.tflite"]
    assert url == ("https://storage.googleapis.com/mediapipe-models/object_detector/efficientdet_lite0/"
                   "float16/latest/efficientdet_lite0.tflite")
