"""디자인 토큰 원본을 서버 복사본(server/app/booth_design/)과 부스 복사본(booth/walnut/booth_design/)으로 옮긴다.

서버는 server/ 폴더만 배포되므로(Docker 빌드 컨텍스트) 원본을 직접 읽을 수 없다.
shared/booth-design 의 tokens.json · booth_tokens.py 를 고쳤다면 저장소 루트에서:

    python shared/booth-design/tools/sync-server.py

server/tests/test_photo_design.py 의 test_server_copy_matches_shared,
booth/tests/test_design_tokens.py 의 test_booth_copy_matches_shared 가 어긋남을 잡는다.

기본 프레임(default-frame/frame.png · frame.json)도 booth/walnut/default_frame/ 로 함께 옮긴다
(booth/tests/test_default_bundle.py 의 test_booth_copy_matches_shared 가 지킨다).
"""

from __future__ import annotations

import shutil
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1]
ROOT = SHARED.parents[1]
TARGETS = (ROOT / "server" / "app" / "booth_design", ROOT / "booth" / "walnut" / "booth_design")
FILES = ("tokens.json", "booth_tokens.py")
INIT = '''"""부스 디자인 토큰 복사본 — 원본은 shared/booth-design (tools/sync-server.py 로 옮긴다)."""

from .booth_tokens import load, resolve_roles, credit_visible
'''


# 기본 프레임 (연결 없이 시작할 때 쓰는 번들의 프레임). 지금은 Python 부스만 복사본을 둔다
FRAME_SRC = SHARED / "default-frame"
FRAME_TARGETS = (ROOT / "booth" / "walnut" / "default_frame",)
FRAME_FILES = ("frame.png", "frame.json")
FRAME_INIT = '"""기본 프레임 복사본 — 원본은 shared/booth-design/default-frame (tools/sync-server.py 로 옮긴다)."""\n'


def sync_default_frame() -> None:
    for target in FRAME_TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        for name in FRAME_FILES:
            shutil.copyfile(FRAME_SRC / name, target / name)
            print(f"복사: {name} → {target / name}")
        init = target / "__init__.py"
        if not init.exists():
            init.write_text(FRAME_INIT, encoding="utf-8")
            print(f"만듦: {init}")


def main() -> None:
    sync_default_frame()
    for target in TARGETS:
        target.mkdir(parents=True, exist_ok=True)
        for name in FILES:
            shutil.copyfile(SHARED / name, target / name)  # 덮어쓴다
            print(f"복사: {name} → {target / name}")
        init = target / "__init__.py"
        if not init.exists():  # 이미 있으면 건드리지 않는다
            init.write_text(INIT, encoding="utf-8")
            print(f"만듦: {init}")


if __name__ == "__main__":
    main()
