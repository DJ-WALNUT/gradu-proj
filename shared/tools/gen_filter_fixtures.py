"""shared/filter_fixtures.json 생성기.

Python 부스(booth/walnut/filters.py)와 TS(shared/compose/filters.ts)가 같은 값을 내는지
대조하는 기대값을 만든다. 수식은 filters.py 와 독립적으로 여기서 다시 계산한다.
실행:  python shared/tools/gen_filter_fixtures.py   (저장소 루트에서, 표준 라이브러리만 사용)

입력 색:
- 0 · 255 · 원색 · 회색 (클리핑 확인: warm 파랑 -14, bright 255 등)
- 경계값: gain*v+bias 의 소수부가 정확히 .5 인 v (float64). 이 v 에서 floor(x+0.5) 가
  올림되는지 확인한다. 채널별 (gain, bias) 로 스캔해 자동으로 찾는다.
  (예: bright 1.12*v+12 가 .5 에 걸리는 v, vintage 0.85*v+38 · 0.85*v+28 · 0.80*v+22)
- 무작위 40개 (random.Random(20261019)) — 필터마다 같은 40개를 쓴다.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "filter_fixtures.json"

FILTERS = ("original", "mono", "bright", "warm", "cool", "vintage")

# booth/walnut/filters.py 의 _PARAMS 와 같은 값 (test_filter_fixtures.py 가 일치를 검사한다).
PARAMS = {
    "original": ((1.0, 0), (1.0, 0), (1.0, 0)),
    "bright": ((1.12, 12), (1.12, 12), (1.12, 12)),
    "warm": ((1.0, 18), (1.0, 4), (1.0, -14)),
    "cool": ((1.0, -14), (1.0, 2), (1.0, 18)),
    "vintage": ((0.85, 38), (0.85, 28), (0.80, 22)),
}


def ch(gain: float, bias: float, v: int) -> int:
    return min(255, max(0, math.floor(gain * v + bias + 0.5)))


def apply(name: str, rgb: tuple[int, int, int]) -> list[int]:
    if name == "mono":
        r, g, b = rgb
        y = min(255, max(0, math.floor(0.299 * r + 0.587 * g + 0.114 * b + 0.5)))
        return [y, y, y]
    params = PARAMS.get(name, PARAMS["original"])
    return [ch(g, b, v) for (g, b), v in zip(params, rgb)]


def half_boundaries(gain: float, bias: float) -> list[int]:
    """gain*v+bias 의 소수부가 정확히 .5 인 v (0~255)."""
    return [v for v in range(256) if (gain * v + bias) % 1 == 0.5]


def inputs_for(name: str, rnd_triples: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
    ins: list[tuple[int, int, int]] = [
        (0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255),
        (128, 128, 128), (127, 127, 127), (1, 1, 1), (254, 254, 254),
    ]
    for c, (g, b) in enumerate(PARAMS.get(name, ())):
        for v in half_boundaries(g, b):
            t = [0, 0, 0]
            t[c] = v
            ins.append((t[0], t[1], t[2]))
            ins.append((v, v, v))
    # mono 가중합 경계 근처 몇 개
    if name == "mono":
        ins += [(1, 1, 0), (0, 1, 1), (2, 0, 0), (0, 0, 5), (3, 0, 0), (0, 0, 4), (255, 255, 0)]
    ins += rnd_triples
    seen, uniq = set(), []
    for t in ins:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def main() -> None:
    rnd = random.Random(20261019)
    rnd_triples = [(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(40)]
    cases = []
    for name in FILTERS:
        for t in inputs_for(name, rnd_triples):
            cases.append({"filter": name, "in": list(t), "out": apply(name, t)})
    body = ",\n".join("    " + json.dumps(c) for c in cases)
    text = '{\n  "version": 1,\n  "cases": [\n' + body + "\n  ]\n}\n"
    assert json.loads(text) == {"version": 1, "cases": cases}
    with OUT.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"{len(cases)} cases -> {OUT}")
    for n, p in PARAMS.items():
        print(n, [half_boundaries(g, b) for g, b in p])


if __name__ == "__main__":
    main()
