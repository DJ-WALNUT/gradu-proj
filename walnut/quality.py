"""후보 평가 · 베스트 컷 선택.

카메라 · 화면 · 서버를 모르는 순수 계산 모듈이다. 얼굴 모델의 출력을 FaceObs 로 바꾼 뒤
버스트(짧은 연속 촬영) 안에서 한 장을 고른다. 같은 입력이면 항상 같은 결과가 나오도록
난수 없이 정해진 순서로만 비교한다.

아래 상수는 모두 실험으로 조정할 값이다. 방향 지표는 고개가 정면에 가까운 정도(frontality)다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

# 실험으로 조정
W_SHARP = 0.4
W_EYE = 0.4
W_POSE = 0.2
BLUR_REJECT = 0.35   # 후보 그룹(얼굴 수가 가장 많은 후보들) 최고 선명도 대비 이 비율 미만이면 제외
SHARP_MIN_RANGE = 0.25  # 선명도 정규화 폭의 하한(최고값 대비). 거의 같은 선명도의 잡음이 0~1 로 부풀지 않게 한다
EYE_REJECT = 0.7     # 눈 뜸 지표가 이 값 미만이면 제외. 한 사람에게서 잰 값(감은 눈 0.45~0.57, 뜬 눈 0.82~0.94)이라 실험으로 조정
POSE_MAX_DEG = 45.0  # 이 각도 이상 돌아가면 방향 점수 0
EAR_CLOSED = 0.12    # 이 값 이하면 눈 뜸 0
EAR_OPEN = 0.28      # 이 값 이상이면 눈 뜸 1

# EAR 점 번호: p1 바깥 모서리, p2 · p3 위, p4 안쪽 모서리, p5 · p6 아래
_EYE_LEFT = (33, 160, 158, 133, 153, 144)
_EYE_RIGHT = (362, 385, 387, 263, 373, 380)


@dataclass
class FaceObs:
    box: tuple[float, float, float, float]  # 0~1 정규화 x0 y0 x1 y1
    eye_open: float | None                  # 0~1, 없으면 None
    frontality: float | None                # 0~1, 없으면 None


@dataclass
class Candidate:
    t: float
    sharpness: float
    faces: list[FaceObs] = field(default_factory=list)


@dataclass
class Selection:
    index: int
    reason: str            # single | no_face | best | all_rejected
    fallback_used: bool
    scores: list[float | None]
    # 후보마다 탈락 사유: faces(얼굴 수 부족) · blur(흔들림) · eye(눈 감음) · None. 고르는 데는 쓰지 않는다 (표시 · 기록용)
    rejects: list[str | None] = field(default_factory=list)


def sharpness(gray: np.ndarray, box=None) -> float:
    """라플라시안 분산. box(0~1 정규화)가 있으면 이미지 안으로 잘라 그 영역만 잰다."""
    h, w = gray.shape[:2]
    if box is not None:
        x0 = max(0, min(w, int(math.floor(box[0] * w))))
        y0 = max(0, min(h, int(math.floor(box[1] * h))))
        x1 = max(0, min(w, int(math.ceil(box[2] * w))))
        y1 = max(0, min(h, int(math.ceil(box[3] * h))))
        if x1 <= x0 or y1 <= y0:
            return 0.0
        gray = gray[y0:y1, x0:x1]
    if gray.size == 0:
        return 0.0
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def _dist(a, b, aspect: float) -> float:
    # 정규화 좌표는 가로세로 비율이 달라 x 에 aspect(가로/세로)를 곱해야 실제 거리가 된다
    return math.hypot((a.x - b.x) * aspect, a.y - b.y)


def _ear_one(lm, idx, aspect: float) -> float:
    p1, p2, p3, p4, p5, p6 = (lm[i] for i in idx)
    width = _dist(p1, p4, aspect)
    if width <= 0:
        return 0.0
    return (_dist(p2, p6, aspect) + _dist(p3, p5, aspect)) / (2 * width)


def eye_aspect_ratio(landmarks, aspect: float = 1.0) -> float:
    """두 눈 중 더 감긴 쪽(작은 값)의 EAR. aspect 는 프레임 가로/세로."""
    return min(_ear_one(landmarks, _EYE_LEFT, aspect), _ear_one(landmarks, _EYE_RIGHT, aspect))


def _clip01(v: float) -> float:
    return max(0.0, min(1.0, v))


def eye_open_from(blendshapes, landmarks, aspect: float = 1.0) -> float | None:
    """눈 뜸 0~1. 블렌드셰이프(1 - max(왼, 오른쪽 깜빡임))를 먼저, 없으면 EAR, 둘 다 없으면 None."""
    if blendshapes:
        scores = {c.category_name: c.score for c in blendshapes}
        if "eyeBlinkLeft" in scores and "eyeBlinkRight" in scores:
            return _clip01(1.0 - max(scores["eyeBlinkLeft"], scores["eyeBlinkRight"]))
    if landmarks is None:
        return None
    ear = eye_aspect_ratio(landmarks, aspect)
    return _clip01((ear - EAR_CLOSED) / (EAR_OPEN - EAR_CLOSED))


def frontality_from(matrix) -> float | None:
    """4x4 변환 행렬에서 고개 방향 0~1 (정면 1). 크기 성분은 정규화로 없앤다. 잘못된 입력은 None."""
    if matrix is None:
        return None
    try:
        m = np.asarray(matrix, dtype=float)
    except (TypeError, ValueError):
        return None
    if m.shape != (4, 4) or not np.all(np.isfinite(m)):
        return None
    rot = m[:3, :3]
    norms = np.linalg.norm(rot, axis=0)
    if np.any(norms <= 1e-9):
        return None
    forward = rot[:, 2] / norms[2]  # 얼굴 앞쪽 축이 카메라 축(z)과 이루는 각
    cos = _clip01(abs(float(forward[2])))
    angle = math.degrees(math.acos(cos))
    return _clip01(1.0 - angle / POSE_MAX_DEG)


def _min_metric(vals: list[float | None]) -> float | None:
    have = [v for v in vals if v is not None]
    return min(have) if have else None


def select_best(cands: list[Candidate], shutter_t: float) -> Selection:
    n = len(cands)
    if n == 0:
        raise ValueError("후보가 없다")
    if n == 1:
        return Selection(0, "single", False, [None], [None])

    def tie_key(i: int):  # 셔터에 가까운 쪽, 그다음 이른 쪽, 그다음 앞 번호
        return (abs(cands[i].t - shutter_t), cands[i].t, i)

    most = max(len(c.faces) for c in cands)
    keep = [i for i in range(n) if len(cands[i].faces) == most]

    # 선명도는 같은 측정끼리만 비교한다 (얼굴 없음은 프레임 전체, 있음은 얼굴 영역을 잰다)
    sharps = [c.sharpness for c in cands]
    group = [sharps[i] for i in keep]
    lo, hi = min(group), max(group)
    span = max(hi - lo, SHARP_MIN_RANGE * hi)
    norm = [max(0.0, (s - lo) / span) if span > 0 else 0.0 for s in sharps]

    if most == 0:
        best = min(range(n), key=lambda i: (-norm[i], *tie_key(i)))
        return Selection(best, "no_face", False, list(norm), [None] * n)

    eyes = {i: _min_metric([f.eye_open for f in cands[i].faces]) for i in keep}
    poses = {i: _min_metric([f.frontality for f in cands[i].faces]) for i in keep}

    rejects: list[str | None] = ["faces"] * n
    for i in keep:
        if hi > 0 and sharps[i] < BLUR_REJECT * hi:
            rejects[i] = "blur"
        elif eyes[i] is not None and eyes[i] < EYE_REJECT:
            rejects[i] = "eye"
        else:
            rejects[i] = None
    ok = [i for i in keep if rejects[i] is None]
    if not ok:
        return Selection(min(keep, key=tie_key), "all_rejected", True, [None] * n, rejects)

    scores: list[float | None] = [None] * n
    for i in ok:
        parts = [(W_SHARP, norm[i])]
        if eyes[i] is not None:
            parts.append((W_EYE, eyes[i]))
        if poses[i] is not None:
            parts.append((W_POSE, poses[i]))
        scores[i] = sum(w * v for w, v in parts) / sum(w for w, _ in parts)

    best = min(ok, key=lambda i: (-scores[i], *tie_key(i)))
    return Selection(best, "best", False, scores, rejects)
