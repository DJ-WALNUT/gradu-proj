"""얼굴 기하와 떨림 보정.

faces 는 FaceLandmarker 결과(얼굴마다 478점, frame 기준 0~1 좌표)다.
스티커를 얹는 일은 stickers.py 가 한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# FaceMesh 인덱스
FOREHEAD, CHIN, NOSE = 10, 152, 1
FACE_EDGE_A, FACE_EDGE_B = 234, 454
EYE_A, EYE_B = 33, 263
CHEEK_A, CHEEK_B = 50, 280


@dataclass
class FaceGeom:
    center: np.ndarray   # 얼굴 중심 (px)
    up: np.ndarray       # 위쪽 단위벡터 (턱 → 이마)
    right: np.ndarray    # 화면 오른쪽 단위벡터 (눈 선 방향)
    width: float         # 얼굴 폭 (px)
    height: float        # 이마~턱 (px)
    roll_deg: float      # 기울기 (PIL rotate 용, 반시계 +)
    edge_l: np.ndarray   # 화면 왼쪽 얼굴 옆선
    edge_r: np.ndarray
    cheek_l: np.ndarray
    cheek_r: np.ndarray
    forehead: np.ndarray
    chin: np.ndarray
    nose: np.ndarray
    eyes: np.ndarray     # 두 눈의 중점


def geometry(face, w: int, h: int) -> FaceGeom:
    def px(i: int) -> np.ndarray:
        return np.array([face[i].x * w, face[i].y * h], dtype=np.float32)

    ea, eb = px(EYE_A), px(EYE_B)
    eye_l, eye_r = (ea, eb) if ea[0] <= eb[0] else (eb, ea)
    right = eye_r - eye_l
    right /= max(1e-6, float(np.linalg.norm(right)))
    up = np.array([right[1], -right[0]], dtype=np.float32)  # 오른쪽을 반시계 90° 돌린 것
    fa, fb = px(FACE_EDGE_A), px(FACE_EDGE_B)
    edge_l, edge_r = (fa, fb) if fa[0] <= fb[0] else (fb, fa)
    ca, cb = px(CHEEK_A), px(CHEEK_B)
    cheek_l, cheek_r = (ca, cb) if ca[0] <= cb[0] else (cb, ca)
    forehead, chin = px(FOREHEAD), px(CHIN)
    return FaceGeom(
        center=(forehead + chin) / 2,
        up=up,
        right=right,
        width=float(np.linalg.norm(edge_r - edge_l)),
        height=float(np.linalg.norm(forehead - chin)),
        roll_deg=-math.degrees(math.atan2(right[1], right[0])),
        edge_l=edge_l, edge_r=edge_r,
        cheek_l=cheek_l, cheek_r=cheek_r,
        forehead=forehead, chin=chin,
        nose=px(NOSE),
        eyes=(ea + eb) / 2,
    )


# ── 떨림 보정 ────────────────────────────────────────────────────────
# 랜드마크는 가만히 있어도 프레임마다 몇 px 씩 흔들린다. 그대로 쓰면 스티커가 움찔거린다.
# One Euro 필터: 느리게 움직일 때는 강하게 다듬고, 빠르게 움직이면 바로 따라간다.
#   SMOOTH_MIN_CUTOFF 를 낮추면 가만히 있을 때 더 차분해진다 (대신 살짝 늦게 따라온다).
#   SMOOTH_BETA 를 높이면 고개를 빨리 돌릴 때 덜 늦는다.
SMOOTH_MIN_CUTOFF = 0.6   # Hz
SMOOTH_BETA = 6.0
HOLD_SECONDS = 0.3        # 인식이 잠깐 끊겨도 이 시간 동안은 마지막 위치를 유지 (깜빡임 방지)
MATCH_DIST = 0.15         # 프레임 사이 같은 얼굴로 볼 중심 거리 (화면 폭 대비)

_KEYS = (FOREHEAD, CHIN, FACE_EDGE_A, FACE_EDGE_B, EYE_A, EYE_B, CHEEK_A, CHEEK_B, NOSE)


class _OneEuro:
    def __init__(self, x: np.ndarray, t: float):
        self.x, self.dx, self.t = x, np.zeros_like(x), t

    @staticmethod
    def _alpha(cutoff, dt: float):
        r = 2 * math.pi * cutoff * dt
        return r / (r + 1)

    def update(self, x: np.ndarray, t: float) -> np.ndarray:
        dt = max(1e-3, t - self.t)
        self.t = t
        dx = (x - self.x) / dt
        self.dx += self._alpha(1.0, dt) * (dx - self.dx)
        cutoff = SMOOTH_MIN_CUTOFF + SMOOTH_BETA * np.abs(self.dx)
        self.x = self.x + self._alpha(cutoff, dt) * (x - self.x)
        return self.x


class _Point:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float):
        self.x, self.y = x, y


class FaceTracker:
    """얼굴마다 핵심 랜드마크를 부드럽게 만든다. 카메라 프레임이 바뀔 때 한 번씩 update()."""

    def __init__(self):
        self.tracks: list[dict] = []  # {"filter": _OneEuro, "seen": t}

    def update(self, faces, t: float) -> list[dict[int, _Point]]:
        """얼굴별 {랜드마크 번호: 점}. 번호는 _KEYS 뿐이다."""
        raw = [np.array([[f[i].x, f[i].y] for i in _KEYS], dtype=np.float64) for f in faces]
        free = list(range(len(self.tracks)))
        for pts in raw:
            c = pts[:2].mean(axis=0)  # 이마·턱 중점
            best = min(free, key=lambda k: np.linalg.norm(self.tracks[k]["filter"].x[:2].mean(axis=0) - c), default=None)
            if best is not None and np.linalg.norm(self.tracks[best]["filter"].x[:2].mean(axis=0) - c) < MATCH_DIST:
                free.remove(best)
                self.tracks[best]["filter"].update(pts, t)
                self.tracks[best]["seen"] = t
            else:
                self.tracks.append({"filter": _OneEuro(pts, t), "seen": t})
        self.tracks = [tr for tr in self.tracks if t - tr["seen"] <= HOLD_SECONDS]
        return [{i: _Point(*p) for i, p in zip(_KEYS, tr["filter"].x)} for tr in self.tracks]
