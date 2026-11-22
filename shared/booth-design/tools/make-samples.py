"""시안 샘플 사진 4장 + 프레임 1장 — 단색 그라데이션과 단순한 도형만 (외부 사진 없음).

    server/.venv/bin/python shared/booth-design/tools/make-samples.py [출력 폴더]   # 기본: mockups/samples
Pillow 가 필요하다 (서버 venv 에 있다).
"""
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "mockups" / "samples"
W, H = 600, 800  # 3:4 세로 컷

def grad(top, bottom, w, h):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img

# 사람 실루엣 비슷한 단순 도형 (머리 원 + 어깨 반원) — 사진 자리임을 알아보게
people = [
    ((236, 214, 222), (201, 207, 224), (120, 98, 110), [(300, 330)]),
    ((214, 226, 236), (238, 222, 206), (92, 108, 128), [(220, 340), (390, 360)]),
    ((240, 228, 204), (222, 206, 226), (128, 104, 84), [(300, 320)]),
    ((210, 232, 220), (232, 218, 236), (84, 118, 100), [(200, 350), (300, 320), (410, 355)]),
]
for i, (top, bottom, ink, heads) in enumerate(people, 1):
    img = grad(top, bottom, W, H)
    d = ImageDraw.Draw(img, "RGBA")
    r = 80 if len(heads) == 1 else (66 if len(heads) == 2 else 52)
    for (cx, cy) in heads:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ink + (200,))
        d.pieslice([cx - r * 2.1, cy + r * 1.3, cx + r * 2.1, cy + r * 5.5], 180, 360, fill=ink + (170,))
    img.save(out / f"photo-{i}.png", optimize=True)

# 4컷 프레임 (2×2), 컷 자리는 투명. 아래 띠에 작은 장식 점.
FW, FH = 1000, 1500
frame = Image.new("RGBA", (FW, FH), (255, 205, 214, 255))
d = ImageDraw.Draw(frame)
m, g, bottom = 50, 40, 170
cw = (FW - 2 * m - g) // 2
ch = (FH - m - bottom - g) // 2
windows = []
for row in range(2):
    for col in range(2):
        x = m + col * (cw + g)
        y = m + row * (ch + g)
        d.rectangle([x, y, x + cw - 1, y + ch - 1], fill=(0, 0, 0, 0))
        windows.append([round(x / FW, 4), round(y / FH, 4), round(cw / FW, 4), round(ch / FH, 4)])
for k in range(5):
    cx = FW / 2 + (k - 2) * 46
    d.ellipse([cx - 9, FH - bottom / 2 - 9, cx + 9, FH - bottom / 2 + 9], fill=(230, 110, 130, 255))
frame.save(out / "frame-4cut.png", optimize=True)

# 행사 로고 자리 — 가로로 긴 투명 PNG (둥근 띠 + 원 셋). 글자 없이 '로고가 있다'는 것만 보인다
LW, LH = 900, 300
logo = Image.new("RGBA", (LW, LH), (0, 0, 0, 0))
d = ImageDraw.Draw(logo)
d.rounded_rectangle([20, 60, LW - 20, LH - 60], radius=(LH - 120) // 2, fill=(27, 37, 80, 255))
for k, col in enumerate([(230, 110, 130, 255), (255, 248, 249, 255), (234, 244, 251, 255)]):
    cx = 180 + k * 150
    d.ellipse([cx - 50, LH / 2 - 50, cx + 50, LH / 2 + 50], fill=col)
d.rounded_rectangle([640, LH / 2 - 22, LW - 90, LH / 2 + 22], radius=22, fill=(255, 248, 249, 255))
logo.save(out / "logo.png", optimize=True)

(out / "samples.json").write_text(json.dumps({
    "photos": [f"photo-{i}.png" for i in range(1, 5)],
    "photo_ratio": [3, 4],
    "frame": {"file": "frame-4cut.png", "ratio": [FW, FH], "windows": windows},
    "logo": {"file": "logo.png", "size": [LW, LH]},
    # 사진 페이지 시안이 흉내 내는 기기 화면 (CSS px) — 휴대폰(9:19.5, 세로 배치) · 노트북 브라우저(가로 배치)
    "devices": {"phone": [390, 844], "desktop": [1280, 720]},
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("ok", windows)
