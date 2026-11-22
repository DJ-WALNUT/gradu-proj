"""영수증 사진 밝기 고르기 — 같은 사진을 감마 · 밝기 · 대비를 바꿔 가며 영수증 한 장에 띠로 나란히 뽑는다.

    .\\.venv\\Scripts\\python tools\\print_tune.py                       # 가장 최근 합성 사진, 기본 5가지
    .\\.venv\\Scripts\\python tools\\print_tune.py --set 0.7,1.1,1.0 --set 0.5,1.2,1.1
    .\\.venv\\Scripts\\python tools\\print_tune.py --photo data\\collage\\x.jpg --preview out.png   # 인쇄 없이 이미지로

마음에 드는 띠의 숫자를 walnut/printer.py 맨 위 PHOTO_GAMMA · PHOTO_BRIGHTNESS · PHOTO_CONTRAST 에 적는다.
포트는 부스와 같다 (.env 의 PRINTER_PORT, 비우면 자동).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw  # noqa: E402

from walnut.printer import PAPER_W, _font, _stack, photo_dots  # noqa: E402

BAND_H = 300      # 사진 띠 높이 (점)
LABEL_H = 44
DEFAULT_SETS = [(1.0, 1.0, 1.0), (0.8, 1.05, 1.0), (0.7, 1.1, 1.0), (0.6, 1.15, 1.0), (0.5, 1.2, 1.1)]


def tune_sheet(photo: Image.Image, settings: list[tuple[float, float, float]]) -> Image.Image:
    """설정마다 '감마 · 밝기 · 대비' 글자 + 사진 띠 (사진 위쪽 1/4 지점부터 BAND_H)."""
    parts = []
    for gamma, bright, contrast in settings:
        dots = photo_dots(photo, gamma=gamma, brightness=bright, contrast=contrast)
        top = min(max(0, dots.height // 4), max(0, dots.height - BAND_H))
        band = dots.crop((0, top, PAPER_W, top + BAND_H))
        label = Image.new("L", (PAPER_W, LABEL_H), 255)
        ImageDraw.Draw(label).text((12, LABEL_H // 2), f"감마 {gamma}  ·  밝기 {bright}  ·  대비 {contrast}",
                                   font=_font(26), fill=0, anchor="lm")
        parts += [label.convert("1", dither=Image.NONE), band]
    return _stack(*parts)


def _parse_set(text: str) -> tuple[float, float, float]:
    g, b, c = (float(x) for x in text.split(","))
    return g, b, c


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="영수증 사진 밝기 비교 인쇄")
    ap.add_argument("--photo", type=Path, help="사진 (기본: data/collage 의 가장 최근 것)")
    ap.add_argument("--set", action="append", type=_parse_set, metavar="감마,밝기,대비", help="여러 번 줄 수 있다")
    ap.add_argument("--preview", type=Path, help="인쇄하지 않고 이 PNG 로 저장")
    args = ap.parse_args(argv)

    photo_path = args.photo
    if photo_path is None:
        shots = sorted((ROOT / "data" / "collage").glob("*.jpg"), key=lambda p: p.stat().st_mtime)
        if not shots:
            print("data/collage 에 사진이 없습니다. --photo 로 지정하세요.")
            return 1
        photo_path = shots[-1]
    sheet = tune_sheet(Image.open(photo_path), args.set or DEFAULT_SETS)
    if args.preview:
        sheet.save(args.preview)
        print(f"저장했습니다: {args.preview}")
        return 0

    from walnut import config
    from walnut.printer import ReceiptPrinter, escpos_chunks

    cfg = config.load()
    p = ReceiptPrinter(cfg.printer_port, start=False)
    port = p.port()
    if port is None:
        print("프린터를 찾지 못했습니다 (.env 의 PRINTER_PORT 확인).")
        return 1
    import serial

    with serial.Serial(port, 38400, timeout=2, write_timeout=10) as s:
        for chunk in escpos_chunks(sheet):
            s.write(chunk)
            s.flush()
            time.sleep(0.05)  # 부스 인쇄와 같은 속도로
    print(f"{port} 로 보냈습니다 ({datetime.now():%H:%M:%S}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
