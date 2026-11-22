"""공통 테스트 도구: fake_server, make_bundle."""

from __future__ import annotations

import copy
import hashlib
import hmac
import io
import json
import os
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image, ImageDraw

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from walnut.settings import DEFAULTS  # noqa: E402


@dataclass
class Req:
    method: str
    path: str
    headers: dict
    body: bytes


class FakeServer:
    """http.server 를 스레드로 띄운 가짜 부스 API. route(method, path, handler) 로 응답을 정한다."""

    def __init__(self) -> None:
        self.requests: list[Req] = []
        self._routes: dict[tuple[str, str], object] = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _handle(self) -> None:
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                path = self.path.split("?")[0]
                req = Req(self.command, path, {k: v for k, v in self.headers.items()}, body)
                outer.requests.append(req)
                fn = outer._routes.get((self.command, path))
                if fn is None:
                    status, headers, out = 404, {}, {"error": "not_found"}
                else:
                    status, headers, out = fn(req)
                headers = dict(headers)
                if isinstance(out, (dict, list)):
                    out = json.dumps(out, ensure_ascii=False).encode()
                    headers.setdefault("Content-Type", "application/json")
                out = out or b""
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                no_body = status in (204, 304)
                self.send_header("Content-Length", "0" if no_body else str(len(out)))
                self.end_headers()
                if not no_body:
                    self.wfile.write(out)

            do_GET = do_POST = do_PUT = do_DELETE = _handle

            def log_message(self, *a) -> None:  # 테스트 출력 조용히
                pass

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def route(self, method: str, path: str, handler) -> None:
        self._routes[(method.upper(), path)] = handler

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


@pytest.fixture
def fake_server():
    s = FakeServer()
    yield s
    s.close()


def _frame_png(w: int = 400, h: int = 600) -> tuple[bytes, list[dict]]:
    """불투명 프레임에 2x2 투명 구멍 4개."""
    img = Image.new("RGBA", (w, h), (255, 200, 210, 255))
    sw, sh = 160, 240
    centers = [(100, 160), (300, 160), (100, 440), (300, 440)]
    d = ImageDraw.Draw(img)
    slots = []
    for i, (cx, cy) in enumerate(centers):
        d.rectangle([cx - sw // 2, cy - sh // 2, cx + sw // 2 - 1, cy + sh // 2 - 1], fill=(0, 0, 0, 0))
        slots.append({"id": i + 1, "shot": i, "cx": cx, "cy": cy, "w": sw, "h": sh, "rot": 0, "ratio": "2:3"})
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue(), slots


def _merge(base: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def _make_bundle(version=1, event_id=1, frames=None, settings_patch=None, key=b"k" * 32):
    """(bundle_bytes, assets{sha: bytes}). frames 를 주면 서버 번들의 frames 항목을 그대로 쓴다 (asset 은 sha)."""
    assets: dict[str, bytes] = {}
    kinds: dict[str, str] = {}
    if frames is None:
        png, slots = _frame_png()
        sha = hashlib.sha256(png).hexdigest()
        assets[sha] = png
        kinds[sha] = "frame"
        frames = [{"id": 1, "name": "기본 프레임", "asset": sha, "width": 400, "height": 600, "slots": slots}]
    settings = copy.deepcopy(DEFAULTS)
    settings["admin"]["pin_hash"] = hmac.new(key, b"482916", "sha256").hexdigest()
    _merge(settings, settings_patch or {})
    for fr in frames:
        kinds.setdefault(fr["asset"], "frame")
    for k in ("logo_asset", "font_asset"):
        if settings["branding"].get(k):
            kinds.setdefault(settings["branding"][k], k.split("_")[0])
    for it in settings["stickers"]["items"]:
        kinds.setdefault(it["asset"], "sticker")
    bundle = {
        "version": version, "published_at": "2026-10-15T09:00:00+09:00",
        "event": {"id": event_id, "name": "테스트 행사"},
        "settings": settings, "frames": frames,
        "assets": [{"sha256": s, "kind": k, "size": len(assets[s]) if s in assets else 0}
                   for s, k in sorted(kinds.items())],
    }
    return json.dumps(bundle, ensure_ascii=False, sort_keys=True).encode(), assets


@pytest.fixture
def make_bundle():
    return _make_bundle


@pytest.fixture
def make_app(tmp_path, fake_server):
    """make_app(env=None, display_size=(1920, 1080)) → App. data_dir 는 tmp_path/data, 카메라는 FakeCamera, 리모컨 끔, 창 모드."""
    from walnut import config
    from walnut.app import App

    apps = []

    def _make(env: dict | None = None, display_size: tuple[int, int] = (1920, 1080)):
        e = {"SERVER_URL": fake_server.url, "BOOTH_FULLSCREEN": "false", "REMOTE_PORT": "off", "BOOTH_MOTION": "false",
             "PRINTER_PORT": "dummy"}  # 실제 프린터가 꽂힌 PC 에서도 시험이 종이를 쓰지 않게
        e.update(env or {})
        cfg = config.load(e, root=tmp_path)
        app = App(cfg, no_camera=True, windowed=True, display_size=display_size)
        apps.append(app)
        return app

    yield _make
    for a in apps:
        a.shutdown()


@pytest.fixture(autouse=True)
def _smart_capture_off_by_default(monkeypatch):
    """실제 기본값은 켬이지만, 시험은 플래그를 주지 않으면 기존 경로(둘 다 끔)를 기준으로 본다."""
    from walnut import config
    monkeypatch.setattr(config, "DEFAULT_BURST", False)
    monkeypatch.setattr(config, "DEFAULT_SMART_CROP", False)


@pytest.fixture(autouse=True)
def _no_local_frame_folder(tmp_path_factory, monkeypatch):
    """시험은 이 PC 의 booth/assets/frame 과 상관없이 기본 프레임 하나로 돈다."""
    from walnut import default_bundle
    monkeypatch.setattr(default_bundle, "FRAME_DIR", tmp_path_factory.mktemp("no_frames") / "missing")
