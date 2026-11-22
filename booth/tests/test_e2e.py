"""실제 서버 왕복 E2E: 페어링 → 번들 동기화 → 합성 → 업로드 → 참가자 페이지 → 폐기.

서버는 서버 venv 의 python 으로 tests/e2e/server_harness.py 를 띄운다 (WALNUT_SERVER_PYTHON 으로 바꿀 수 있음).
실행: pytest -m e2e -q
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import requests
from PIL import Image

import walnut
from walnut.api import BoothApi, pair
from walnut.bundle import BundleStore
from walnut.compose import compose, save_jpeg
from walnut.sync import SyncWorker
from walnut.uploader import DONE, Uploader, new_token

ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).resolve().parent / "e2e" / "server_harness.py"


def _server_python() -> Path:
    env = os.environ.get("WALNUT_SERVER_PYTHON")
    if env:
        return Path(env)
    venv = ROOT / "server" / ".venv"
    return venv / "Scripts" / "python.exe" if sys.platform == "win32" else venv / "bin" / "python"


SERVER_PY = _server_python()

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not SERVER_PY.exists(), reason=f"서버 python 없음: {SERVER_PY}"),
]


class Harness:
    """하네스 프로세스. 표준출력 줄을 스레드로 읽어 큐에 넣는다."""

    def __init__(self, data: Path, log: Path) -> None:
        self.log_path = log
        self._log = open(log, "wb")
        self.proc = subprocess.Popen(
            [str(SERVER_PY), str(HARNESS), "--data", str(data)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
            text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self._lines: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()
        try:
            ready = self.read_json(60)
            self.url: str = ready["url"]
            self.code: str = ready["code"]
        except BaseException:  # 준비 실패여도 프로세스는 남기지 않는다
            self.close()
            raise

    def _read(self) -> None:
        for line in self.proc.stdout:
            self._lines.put(line)
        self._lines.put("")  # 프로세스가 끝남 → 기다리지 않고 바로 실패

    def read_json(self, timeout: float) -> dict:
        try:
            line = self._lines.get(timeout=timeout)
        except queue.Empty:
            line = ""
        if not line:
            log = self.log_path.read_text(encoding="utf-8", errors="replace")[-3000:]
            raise AssertionError(f"하네스 응답 없음 (종료 코드 {self.proc.poll()})\n{log}")
        return json.loads(line)

    def command(self, cmd: str, timeout: float = 15) -> dict:
        self.proc.stdin.write(cmd + "\n")
        self.proc.stdin.flush()
        return self.read_json(timeout)

    def close(self) -> None:
        self.proc.kill()
        self.proc.wait(timeout=10)
        self._log.close()


@pytest.fixture
def server(tmp_path):
    h = Harness(tmp_path / "server-data", tmp_path / "server.log")
    try:
        yield h
    finally:
        h.close()


def _status() -> dict:
    return {"outbox": 0, "camera_ok": True, "fps": 30.0, "remote_ok": False}


def test_round_trip_against_real_server(server, tmp_path):
    data = tmp_path / "booth-data"

    # 페어링 → 번들 동기화 → 적용
    device = pair(server.url, server.code, walnut.__version__)
    api = BoothApi(device)
    store = BundleStore(data)
    revoked = threading.Event()
    sync = SyncWorker(api, store, _status, None, revoked.set)
    sync.run_once()
    assert sync.online and sync.last_error == ""
    assert sync.ready_version is not None
    bundle = store.activate(sync.ready_version)
    assert bundle.event_id == device.event_id
    frame = bundle.frames[0]
    assert len(frame["slots"]) == 4

    # 번들의 프레임 + 단색 컷 4장 → 합성
    frame_png = Image.open(store.asset_path(frame["asset"]))
    cuts = [Image.new("RGB", (1200, 900), c) for c in ((220, 40, 40), (40, 200, 40), (40, 40, 220), (230, 200, 30))]
    out = compose(frame_png, frame["slots"], cuts)
    assert out.size == (frame["width"], frame["height"])
    collage = data / "collage"
    collage.mkdir(parents=True)
    jpg = collage / "shot.jpg"
    save_jpeg(out, jpg)

    # 업로드 → 참가자 페이지
    up = Uploader(data / "outbox", api, revoked.set, backoff_base=0.05, backoff_max=0.2)
    up.start()
    try:
        token = new_token()
        up.enqueue(token, jpg)
        assert up.wait_idle(15)
        assert up.state(token) == DONE

        r = requests.get(f"{server.url}/p/{token}", timeout=10)
        assert r.status_code == 200
        r = requests.get(f"{server.url}/p/{token}/image", timeout=10)
        assert r.status_code == 200
        assert r.content[:3] == b"\xff\xd8\xff"

        # 같은 토큰 재업로드(409)도 성공으로 친다
        api.upload_photo(token, jpg.read_bytes())
        up.enqueue(token, jpg)
        assert up.wait_idle(15)
        assert up.state(token) == DONE
        assert not list((data / "outbox").glob("failed/*"))
    finally:
        up.stop()

    # 관리자 폐기 → 다음 동기화에서 연결 해제
    assert server.command("revoke") == {"revoked": 1}
    sync.run_once()
    assert revoked.is_set()
