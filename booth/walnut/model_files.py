"""MediaPipe 모델 파일 — 없으면 내려받는다 (tools/download_models.py 와 개발자 모드가 함께 쓴다).

얼굴 모델(face_landmarker.task, 약 4MB)과 사람 찾기 모델(efficientdet_lite0.tflite, 약 7MB) 두 개다.
"""

from __future__ import annotations

import ssl
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

BASE = "https://storage.googleapis.com/mediapipe-models"
MODELS = {
    "face_landmarker.task": f"{BASE}/face_landmarker/face_landmarker/float16/latest/face_landmarker.task",
    # 얼굴을 못 찾은 사람의 위치 (구도용, walnut/analysis.py 사람 찾기)
    "efficientdet_lite0.tflite": f"{BASE}/object_detector/efficientdet_lite0/float16/latest/efficientdet_lite0.tflite",
}
MIN_BYTES = 1_000_000  # 진짜 모델은 수 MB 다. 이보다 작으면 로그인 페이지나 끊긴 파일로 본다


def _ssl_context() -> ssl.SSLContext:
    """python.org 의 macOS Python 은 시스템 인증서를 쓰지 않는다 — requests 와 함께 깔리는 certifi 를 쓴다."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, context=_ssl_context(), timeout=60) as r, open(dest, "wb") as f:
        want = r.headers.get("Content-Length")
        size = 0
        while chunk := r.read(1 << 16):
            f.write(chunk)
            size += len(chunk)
    # 연결이 중간에 끊겨도 read 는 예외 없이 빈 값으로 끝난다 — 크기로 확인한다
    if want is not None and str(want).isdigit() and size != int(want):
        raise OSError(f"내려받다가 끊겼습니다 ({size} / {want} 바이트)")


def looks_valid(path: Path, name: str | None = None) -> bool:
    """모델 파일처럼 보이는가. 로그인 페이지 · 끊긴 파일을 걸러 낸다. 종류는 name(없으면 path) 의 확장자로 정한다.

    .task 는 충분한 크기의 zip, .tflite 는 충분한 크기에 4~8번째 바이트가 'TFL3' (FlatBuffer 파일 표지).
    """
    kind = Path(name or path.name).suffix
    try:
        if path.stat().st_size < MIN_BYTES:
            return False
        if kind == ".tflite":
            with open(path, "rb") as f:
                return f.read(8)[4:8] == b"TFL3"
        return zipfile.is_zipfile(path)
    except OSError:
        return False


def ensure(models_dir: Path, on_start: Callable[[str], None] | None = None) -> list[str]:
    """없거나 깨진 모델만 받아 그 이름들을 돌려준다. 받기 직전에 on_start(이름) 을 부른다.

    실패는 모두 OSError — 반쯤 받은 파일이나 모델이 아닌 파일은 남기지 않는다.
    """
    out = Path(models_dir)
    out.mkdir(parents=True, exist_ok=True)
    got: list[str] = []
    for name, url in MODELS.items():
        path = out / name
        if looks_valid(path):
            continue
        tmp = path.with_suffix(".part")
        if on_start is not None:
            on_start(name)
        try:
            _download(url, tmp)
            if not looks_valid(tmp, name):
                raise OSError(f"받은 파일이 모델이 아닙니다: {name} (로그인이 필요한 네트워크일 수 있어요)")
            tmp.replace(path)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        except BaseException as exc:  # http.client 오류 · Ctrl+C 등 — 조각을 남기지 않는다
            tmp.unlink(missing_ok=True)
            if isinstance(exc, Exception):
                raise OSError(f"{type(exc).__name__}: {exc}") from exc
            raise
        got.append(name)
    return got
