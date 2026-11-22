"""AR 테스트용 가짜 얼굴 (478점)."""

from __future__ import annotations

import math
from types import SimpleNamespace as P

# 정면 얼굴의 중심 기준 오프셋 (폭 0.16 · 높이 0.2 일 때). w·h 배율로 늘린다.
_BASE = {10: (0, -0.1), 152: (0, 0.1), 234: (-0.08, 0), 454: (0.08, 0), 1: (0, 0.03),
         33: (-0.04, -0.02), 263: (0.04, -0.02), 50: (-0.05, 0.03), 280: (0.05, 0.03)}


def fake_face(cx=0.5, cy=0.5, w=0.16, h=0.2, roll=0.0):
    """roll: 화면에서 반시계로 기울인 각도(도). 정사각 프레임에서 쓴다."""
    th = math.radians(roll)
    c, s = math.cos(th), math.sin(th)
    pts = [P(x=cx, y=cy) for _ in range(478)]
    for i, (dx, dy) in _BASE.items():
        dx, dy = dx * w / 0.16, dy * h / 0.2
        pts[i] = P(x=cx + dx * c + dy * s, y=cy - dx * s + dy * c)
    return pts


# EAR 계산에 쓰는 눈 점 번호 (p1 바깥 모서리, p2·p3 위, p4 안쪽 모서리, p5·p6 아래).
EYE_LEFT = (33, 160, 158, 133, 153, 144)
EYE_RIGHT = (362, 385, 387, 263, 373, 380)


def with_eyes(pts, open_ratio, aspect=1.0, eye_w=0.06, left_ratio=None):
    """fake_face 의 점에 눈 6점씩을 더한다 (제자리 수정 후 반환).

    eye_w 는 프레임 높이 기준 실제 눈 너비, open_ratio 는 높이/너비라서 EAR 과 같다.
    aspect(가로/세로) 가 1 이 아니면 x 를 정규화 좌표로 줄여 담는다.
    left_ratio 를 주면 왼눈만 따로 정한다.
    """
    for idx, cx, ratio in ((EYE_LEFT, 0.44, open_ratio if left_ratio is None else left_ratio),
                           (EYE_RIGHT, 0.56, open_ratio)):
        cy, hh = 0.45, ratio * eye_w / 2
        real = [(-eye_w / 2, 0), (-eye_w / 6, -hh), (eye_w / 6, -hh),
                (eye_w / 2, 0), (eye_w / 6, hh), (-eye_w / 6, hh)]
        for i, (dx, dy) in zip(idx, real):
            pts[i] = P(x=cx + dx / aspect, y=cy + dy)
    return pts
