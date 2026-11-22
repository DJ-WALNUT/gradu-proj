"""shared/compose_fixtures.json 생성기.

관리자 웹(TS) 구현과 독립적으로, compose-rules 의 수식을 그대로 옮겨 기대값을 계산한다.
실행:  python shared/tools/gen_compose_fixtures.py   (저장소 루트에서, 표준 라이브러리만 사용)
crop 계산에는 round() 를 쓰지 않는다 — floor(v + 0.5) 만 쓴다 (JS Math.floor 와 같은 결과).
ar = w / h 를 먼저 float 로 계산하고 ph * ar, pw / ar 순서를 지킨다 (분수·Decimal 금지 — JS 와 같은 float 결과).
crop 크기는 최소 1px.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "compose_fixtures.json"


def slot_corners(cx: float, cy: float, w: float, h: float, rot: float) -> list[list[float]]:
    t = rot * math.pi / 180
    c, s = math.cos(t), math.sin(t)
    local = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    out = []
    for x, y in local:
        # 6자리 반올림 (저장용). + 0.0 으로 -0.0 을 0.0 으로 바꾼다.
        out.append([round(cx + x * c - y * s, 6) + 0.0, round(cy + x * s + y * c, 6) + 0.0])
    return out


def cover_crop(pw: int, ph: int, w: float, h: float) -> dict:
    ar = w / h
    if pw / ph > ar:
        cw = max(1, math.floor(ph * ar + 0.5))
        ch = ph
        x = math.floor((pw - cw) / 2)
        y = 0
    else:
        cw = pw
        ch = max(1, math.floor(pw / ar + 0.5))
        x = 0
        y = math.floor((ph - ch) / 2)
    return {"x": x, "y": y, "w": cw, "h": ch}


# (이름, 슬롯, 사진(w, h))
CASES = [
    ("upright 3:4", dict(cx=512, cy=680, w=812, h=1082, rot=0), (1440, 1080)),
    ("rot 90, 4:3 slot, wider photo", dict(cx=600, cy=900, w=800, h=600, rot=90), (1920, 1080)),
    ("rot -15, 3:4 slot, taller photo", dict(cx=400.5, cy=620.25, w=600, h=800, rot=-15), (1080, 1920)),
    ("rot 30.5, 2:3 slot", dict(cx=1000, cy=1500, w=400, h=600, rot=30.5), (1440, 1080)),
    ("rot 180, 3:2 slot", dict(cx=900, cy=300, w=750, h=500, rot=180), (1440, 1080)),
    ("same ratio 4:3", dict(cx=500, cy=400, w=400, h=300, rot=0), (1200, 900)),
    ("1:1 slot, wider photo", dict(cx=300, cy=300, w=500, h=500, rot=0), (1440, 1080)),
    ("1:1 slot rot -45, taller photo", dict(cx=700, cy=700, w=420, h=420, rot=-45), (1080, 1350)),
    ("16:9 slot, narrower photo", dict(cx=960, cy=540, w=1600, h=900, rot=0), (1440, 1080)),
    # ph*ar = 540.5 → floor(+0.5) = 541 (은행원 반올림이면 540), pw-cw = 899 (홀수) → x = 449
    ("half boundary wide branch, odd offset", dict(cx=250, cy=500, w=500, h=1000, rot=0), (1440, 1081)),
    # pw/ar = 540.5 → ch = 541, ph-ch = 899 (홀수) → y = 449
    ("half boundary tall branch, odd offset", dict(cx=500, cy=250, w=1000, h=500, rot=0), (1081, 1440)),
    # 작은 수의 경계: ph*ar = 6.5 → 7 (은행원 반올림이면 6), pw-cw = 93 → x = 46
    ("tiny half boundary", dict(cx=10, cy=20, w=1, h=2, rot=0), (100, 13)),
    ("free ratio fractional rot 12.3", dict(cx=333.3, cy=444.4, w=517, h=389, rot=12.3), (1440, 1080)),
    # float 계산 순서 고정: ar = 0.35 (float) → 1350 * ar = 472.49999999999994 → 472 (1350*350/1000 = 472.5 면 473)
    ("float order wide branch", dict(cx=200, cy=600, w=350, h=1000, rot=0), (1080, 1350)),
    # 1350 / (600/850) = 1912.4999999999998 → 1912 (1350*850/600 = 1912.5 면 1913)
    ("float order tall branch", dict(cx=400, cy=500, w=600, h=850, rot=0), (1350, 1920)),
    # 극단 비율: floor(1440 * 0.00025 + 0.5) = 0 → 최소 1px
    ("extreme thin slot, min 1px width", dict(cx=500, cy=2000, w=1, h=4000, rot=0), (1080, 1440)),
    ("extreme flat slot, min 1px height", dict(cx=2000, cy=500, w=4000, h=1, rot=0), (1440, 1080)),
]


def main() -> None:
    cases = []
    for name, slot, (pw, ph) in CASES:
        cases.append({
            "name": name,
            "slot": slot,
            "photo": {"w": pw, "h": ph},
            "corners": slot_corners(slot["cx"], slot["cy"], slot["w"], slot["h"], slot["rot"]),
            "crop": cover_crop(pw, ph, slot["w"], slot["h"]),
        })
    # 한 케이스 = 한 줄 (diff 를 읽기 쉽게)
    body = ",\n".join("    " + json.dumps(c, ensure_ascii=False) for c in cases)
    text = '{\n  "version": 1,\n  "cases": [\n' + body + "\n  ]\n}\n"
    assert json.loads(text) == {"version": 1, "cases": cases}
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"{len(cases)} cases -> {OUT}")


if __name__ == "__main__":
    main()
