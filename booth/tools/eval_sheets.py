"""4조건 비교 평가 도구(eval_capture.py)의 출력 도우미 — 가린 비교 시트 · 답안 · 사람 평가 · 디버그 그림.

시트 · 디버그 그림은 원본 얼굴 사진이 담긴다. 이 모듈은 로컬 파일만 쓰고 아무것도 업로드하지 않는다.
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from walnut.compose import compose
from walnut.framing import home_crop, usable_faces

CONDITIONS = ("baseline", "A", "B", "AB")
LABEL_COLS = ("눈감음", "흐림", "잘림", "구도선호")
SHEET_H = 900       # 가린 비교 시트에서 합성 한 장의 높이
LABEL_BAND = 90     # 번호를 적는 위쪽 띠 높이


# ---- 가린 비교 시트 · 답안 ----

def _composite(frame_png: Image.Image, slots: list[dict], r) -> Image.Image:
    crops = {s.slot: s.crop for s in r.slots}
    cut = Image.fromarray(r.rgb)
    cuts = [cut] * (max(s["shot"] for s in slots) + 1)
    return compose(frame_png, slots, cuts, crop_for=lambda slot, _c: crops[slot["id"]])


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # 옛 Pillow
        return ImageFont.load_default()


def blind_sheet(images: list[Image.Image]) -> Image.Image:
    """합성본들을 같은 높이로 맞춰 가로로 이어 붙이고, 위쪽 띠에 1 ~ n 번호만 적는다."""
    scaled = [im.resize((max(1, round(im.width * SHEET_H / im.height)), SHEET_H), Image.BICUBIC)
              for im in images]
    gap = 24
    width = sum(im.width for im in scaled) + gap * (len(scaled) + 1)
    sheet = Image.new("RGB", (width, SHEET_H + LABEL_BAND + gap), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    font = _font(64)
    x = gap
    for n, im in enumerate(scaled, start=1):
        draw.text((x + im.width // 2, LABEL_BAND // 2), str(n), fill=(20, 20, 20), font=font, anchor="mm")
        sheet.paste(im, (x, LABEL_BAND))
        x += im.width + gap
    return sheet


def read_key(path: Path) -> dict[str, dict[int, str]]:
    """blind_key.csv → {시퀀스: {번호: 조건}}. 없으면 빈 dict."""
    path = Path(path)
    if not path.is_file():
        return {}
    key: dict[str, dict[int, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                key.setdefault(row["시퀀스"], {})[int(row["번호"])] = row["조건"]
            except (KeyError, TypeError, ValueError):
                continue
    return key


def blind_order(seq_id: str, shown: list[str], old: dict[int, str] | None, seed, reshuffle: bool) -> list[str]:
    """시트에 놓을 조건 순서. 예전 답안이 같은 조건들을 다루면 그대로 쓴다 (--reshuffle 이면 새로 섞는다)."""
    if old and not reshuffle and sorted(old.values()) == sorted(shown):
        return [old[k] for k in sorted(old)]
    rng = random.Random(f"{seed}:{seq_id}") if seed is not None else random.Random()
    order = list(shown)
    rng.shuffle(order)
    return order


def write_key(path: Path, key: dict[str, list[str]]) -> None:
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["시퀀스", "번호", "조건"])
        for seq_id in sorted(key):
            for n, cond in enumerate(key[seq_id], start=1):
                w.writerow([seq_id, n, cond])


# ---- 사람 평가 ----

def read_labels(root: Path, key: dict[str, list[str]], log) -> dict[str, dict]:
    """<root>/labels.csv 를 답안으로 조건별로 모은다. {조건: {"n": 줄 수, 열: [값...]}}. 파일이 없으면 {}."""
    path = Path(root) / "labels.csv"
    if not path.is_file():
        return {}
    agg = {c: {"n": 0, **{col: [] for col in LABEL_COLS}} for c in CONDITIONS}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            seq_id = (row.get("시퀀스") or "").strip()
            num = (row.get("번호") or "").strip()
            try:
                cond = key[seq_id][int(num) - 1]
                if int(num) < 1:
                    raise IndexError
            except (KeyError, ValueError, IndexError):
                log(f"사람 평가 줄을 답안에서 찾지 못해 건너뜀: 시퀀스 {seq_id or '-'} 번호 {num or '-'}")
                continue
            agg[cond]["n"] += 1
            for col in LABEL_COLS:
                v = (row.get(col) or "").strip()
                if not v:
                    continue
                try:
                    agg[cond][col].append(float(v))
                except ValueError:
                    log(f"사람 평가 값이 숫자가 아니라 건너뜀: {seq_id} {num} {col}={v}")
    return agg


# ---- 디버그 그림 ----

def _dashed_rect(draw: ImageDraw.ImageDraw, box, color, width: int, dash: int = 10) -> None:
    x0, y0, x1, y1 = box
    for a, b, horizontal, fixed in ((x0, x1, True, y0), (x0, x1, True, y1), (y0, y1, False, x0), (y0, y1, False, x1)):
        for s in range(int(a), int(b), dash * 2):
            e = min(b, s + dash)
            draw.line([(s, fixed), (e, fixed)] if horizontal else [(fixed, s), (fixed, e)], fill=color, width=width)


def draw_debug(r, slot: dict, sr, path: Path) -> None:
    """프레임 위에 얼굴 박스(구도에 쓰는 얼굴 초록 · 뺀 얼굴 회색), 기본 구도(점선), 결과 크롭(실선), reason · zoom."""
    img = Image.fromarray(r.rgb).convert("RGB")
    pw, ph = img.size
    draw = ImageDraw.Draw(img)
    width = max(1, round(min(pw, ph) / 300))
    used = usable_faces(r.faces)
    for f in r.faces:
        color = (80, 220, 80) if any(f is u for u in used) else (160, 160, 160)
        draw.rectangle([f.box[0] * pw, f.box[1] * ph, f.box[2] * pw, f.box[3] * ph], outline=color, width=width)
    hx, hy, hw, hh = home_crop(pw, ph, slot["w"], slot["h"])
    _dashed_rect(draw, (hx, hy, hx + hw - 1, hy + hh - 1), (255, 210, 60), width)
    x, y, w, h = sr.crop
    draw.rectangle([x, y, x + w - 1, y + h - 1], outline=(255, 60, 160), width=width * 2)
    draw.text((8, 8), f"{r.condition} {sr.slot}  {sr.reason}  x{sr.zoom:.2f}", fill=(255, 255, 255),
              font=_font(max(12, ph // 24)), stroke_width=2, stroke_fill=(0, 0, 0))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=90)
