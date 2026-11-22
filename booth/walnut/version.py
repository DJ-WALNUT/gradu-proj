"""앱 버전. 설치 zip 에는 빌드 때 만든 VERSION 파일(예: 0.1.0+a1b2c3d)이 들어 있다.

서버에 알리는 app_version 이 이 값이라, 관리자 웹 부스 목록에서 부스마다 어느 빌드인지 보인다.
저장소에서 바로 실행하면 VERSION 이 없으므로 walnut.__version__.
"""

from __future__ import annotations

import re
from pathlib import Path

import walnut

VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"
_OK = re.compile(r"[0-9A-Za-z.+_-]{1,40}")


def app_version() -> str:
    try:
        v = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return walnut.__version__
    return v if _OK.fullmatch(v) else walnut.__version__
