"""MediaPipe 얼굴 모델 내려받기 (최초 1회). 행사장 인터넷에 기대지 않도록 미리 받아 둔다.

    python tools/download_models.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from walnut import model_files  # noqa: E402


def main() -> None:
    try:
        got = model_files.ensure(ROOT / "models", on_start=lambda name: print(f"  받는 중: {name}", flush=True))
    except OSError as exc:
        sys.exit(f"  실패: {exc}")
    for name in model_files.MODELS:
        print(f"  {'받음' if name in got else '있음'}: {name}")
    print("완료")


if __name__ == "__main__":
    main()
