"""얼굴 기반 크롭 계산.

카메라 · 화면을 모르는 순수 계산 모듈이다. 컷 한 장(pw x ph)에서 슬롯 비율의 크롭 영역을
고른다. 아이폰 센터 스테이지처럼 평소에는 가운데를 조금 확대한 '기본 구도(home)' 를 쓰고
(촬영 중 미리보기도 이 구도로 고정), 사람이 가운데(목표점 데드존)를 벗어나면 같은 배율로 그쪽을
따라가 칸 가운데로 오게 하고, 좌우로 퍼져 기본 구도 밖으로 나가면 확대를 풀어 모두 담는다.
얼굴을 못 찾으면 사람이 어디 있는지 모르므로 가장 넓게(1.0배 가운데 = cover_crop) 담는다.
후보를 정해진 순서로만 훑으므로 같은 입력이면 같은 결과가 나온다.

reason 값 (Crop.reason):
  no_face      쓸 얼굴이 없어 가장 넓게 (1.0배 가운데 = cover_crop, fallback_used=True)
  unavailable  얼굴 정보가 없거나 계산이 실패해 가장 넓게 (SmartCropper 만, fallback_used=True)
  home         모든 얼굴이 기본 구도 안이고 얼굴 전체 중심이 목표점 데드존 안이라 그대로
  follow       기본 배율 그대로 위치만 옮김
  widen        기본보다 덜 확대 (퍼진 일행 · 얼굴이 MAX_FACES 이상)
  zoomed       기본보다 더 확대 (작은 얼굴)
  as_shot      손님이 '찍은 그대로' 를 고른 컷 — 얼굴과 상관없이 기본 구도 (SmartCropper 만)

아래 상수는 모두 실험으로 조정할 값이다.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image

from .compose import cover_crop
from .quality import FaceObs

log = logging.getLogger(__name__)

# 실험으로 조정
BASE_ZOOM = 1.3            # 기본 구도: 가운데 크롭을 이만큼 확대 (미리보기도 이 구도)
SMALL_FACE_RATIO = 0.4     # 가장 큰 얼굴 박스 높이의 이 비율보다 작은 얼굴은 뒤쪽 행인으로 보고 뺀다
ZOOMS = tuple(round(1.0 + 0.1 * i, 1) for i in range(11))  # 1.0 ~ 2.0
MAX_UPSCALE = 1.6          # slot_h / crop_h 가 이 값을 넘는 후보는 버린다
GRID = 17                  # 확대 단계마다 가로 · 세로 후보 위치 수
W_CUT, W_OCCLUDE, W_FILL, W_CENTER, W_ZOOM = 5.0, 1.0, 2.0, 1.0, 0.5  # 장식 회피는 사람 담기보다 가볍게
MIN_GAIN = 0.02            # 얼굴이 기본 구도 안일 때, 총비용이 이만큼 낮아야 기본보다 더 확대한다
TARGET = (0.5, 0.42)       # 얼굴 전체 중심이 크롭 안에서 놓일 곳 (가로, 세로 비율)
HOME_DEADBAND = (0.08, 0.10)  # 기본 구도에서 얼굴 전체 중심이 TARGET 에서 이만큼(크롭 폭 · 높이 대비) 안이면 그대로 둔다.
                           # 그 밖이면 같은 배율로 따라간다. 1080p 부스 슬롯 기본 구도(약 624x831)에서 가로 약 50px ·
                           # 세로 약 83px — 가운데 선 사람이 조금 움직여도 구도가 흔들리지 않을 만큼만. 세로를 넓게 둔 것은
                           # 키 · 자세 차이가 크고, 기본 구도 가운데(0.5)에 얼굴이 있어도 TARGET(0.42)에서 0.08 이라서다
FILL_TARGET = 0.35         # 얼굴 전체 박스가 크롭에서 차지해야 할 최소 비율
FAR_FILL = 0.25            # 기본 구도에서 얼굴 전체 박스가 이 비율보다 작을 때만(멀리 선 사람) 기본보다 더 확대한다.
                           # 1080p · 3:4 기본 구도(가로 약 624px): 얼굴 너비 0.10 (0.31) 이상은 그대로, 0.08 (0.25) 이하는 확대.
                           # 처음 0.17 이었는데 2026-11-21 행사(광각)에서 손님 얼굴 너비가 0.05~0.09 라 대부분 1.3배에 머물러
                           # 얼굴 높이가 칸의 약 20% 로 작게 보였다. 그 기록으로 다시 계산하면 0.25 에서 중앙값 약 25%
FACE_PAD = (0.15, 0.35, 0.15, 0.10)  # 얼굴 박스 여백: 좌 · 위 · 우 · 아래 (얼굴 크기 비율)
MAX_FACES = 4              # BurstAnalyzer.max_faces 와 같다. 이 수 이상이면 더 있을 수 있어 가장 넓게(배율 1.0)


@dataclass
class Crop:
    x: int
    y: int
    w: int
    h: int
    reason: str
    fallback_used: bool
    cost: float


def _padded(box) -> tuple[float, float, float, float]:
    w, h = box[2] - box[0], box[3] - box[1]
    return (max(0.0, box[0] - FACE_PAD[0] * w), max(0.0, box[1] - FACE_PAD[1] * h),
            min(1.0, box[2] + FACE_PAD[2] * w), min(1.0, box[3] + FACE_PAD[3] * h))


def _cost(crop: tuple[int, int, int, int], pw: int, ph: int, zoom: float,
          faces: list[FaceObs], occlusion=None) -> tuple[float, float]:
    """(총비용, cut 비용). 모든 항목은 0~1 로 맞춘 뒤 가중합한다."""
    cx, cy, cw, ch = crop
    cut = 0.0
    for f in faces:
        x0, y0, x1, y1 = _padded(f.box)
        x0, x1, y0, y1 = x0 * pw, x1 * pw, y0 * ph, y1 * ph
        area = (x1 - x0) * (y1 - y0)
        if area <= 0:
            continue
        inside = (max(0.0, min(x1, cx + cw) - max(x0, cx))
                  * max(0.0, min(y1, cy + ch) - max(y0, cy)))
        cut = max(cut, 1.0 - inside / area)

    # 원본 박스가 0~1 을 벗어나도 합집합이 컷 안에 머물게 자른다 (_padded 와 같다)
    ux0 = min(max(0.0, f.box[0]) for f in faces) * pw
    uy0 = min(max(0.0, f.box[1]) for f in faces) * ph
    ux1 = max(min(1.0, f.box[2]) for f in faces) * pw
    uy1 = max(min(1.0, f.box[3]) for f in faces) * ph
    rel_x = ((ux0 + ux1) / 2 - cx) / cw
    rel_y = ((uy0 + uy1) / 2 - cy) / ch
    center = min(1.0, math.hypot(rel_x - TARGET[0], rel_y - TARGET[1]) / 0.5)
    fill_ratio = max((ux1 - ux0) / cw, (uy1 - uy0) / ch)
    fill = max(0.0, (FILL_TARGET - fill_ratio) / FILL_TARGET)
    zoom_cost = abs(zoom - BASE_ZOOM) / (ZOOMS[-1] - ZOOMS[0])  # 기본 배율에서 멀수록

    occlude = _occlude(crop, pw, ph, faces, occlusion) if occlusion is not None else 0.0

    total = W_CUT * cut + W_OCCLUDE * occlude + W_FILL * fill + W_CENTER * center + W_ZOOM * zoom_cost
    return total, cut


def _occlude(crop, pw: int, ph: int, faces: list[FaceObs], grid) -> float:
    """얼굴(여백 없는 박스)이 슬롯 안에서 차지할 자리 중 장식에 가려지는 비율의 최댓값.

    컷 픽셀 박스를 크롭을 거쳐 슬롯 정규화 좌표로 옮기고, 그 영역에 걸친 격자 칸의 평균을 쓴다.
    크롭 밖으로 나간 부분은 잘림(cut) 비용이 다루므로 여기서는 자른다.
    """
    cx, cy, cw, ch = crop
    rows, cols = grid.shape
    worst = 0.0
    for f in faces:
        nx0 = max(0.0, (max(0.0, f.box[0]) * pw - cx) / cw)
        nx1 = min(1.0, (min(1.0, f.box[2]) * pw - cx) / cw)
        ny0 = max(0.0, (max(0.0, f.box[1]) * ph - cy) / ch)
        ny1 = min(1.0, (min(1.0, f.box[3]) * ph - cy) / ch)
        if nx1 <= nx0 or ny1 <= ny0:
            continue
        c0, c1 = int(nx0 * cols), min(cols, math.ceil(nx1 * cols))
        r0, r1 = int(ny0 * rows), min(rows, math.ceil(ny1 * rows))
        if c1 <= c0 or r1 <= r0:
            continue
        worst = max(worst, float(grid[r0:r1, c0:c1].mean()))
    return worst


def occlusion_grid(frame_png: Image.Image, slot: dict, cols: int = 48) -> np.ndarray:
    """슬롯 기준 장식 가림 격자. 값 0~1 = 칸 안의 불투명 비율.

    슬롯 자체 좌표(사진 조각을 돌리기 전의 똑바른 방향)로 만든다. 격자는 가로 cols 칸,
    세로 round(cols * slot_h / slot_w) 칸 (최소 1) 이라 shape 는 (rows, cols).
    compose 는 사진을 PIL rotate(-rot) 으로 돌려 붙인다 (rot 은 시계 방향). 프레임을
    rotate(+rot) 으로 반대로 돌리면 슬롯이 똑바로 선다.
    알파 128 이상을 불투명으로 보고, 3픽셀 열기로 몇 픽셀짜리 잔티를 지운다.
    """
    w, h = slot["w"], slot["h"]
    rows = max(1, round(cols * h / w))
    upright = frame_png.convert("RGBA").rotate(slot.get("rot", 0), Image.BICUBIC,
                                               center=(slot["cx"], slot["cy"]))
    x0, y0 = round(slot["cx"] - w / 2), round(slot["cy"] - h / 2)
    region = upright.crop((x0, y0, x0 + max(1, round(w)), y0 + max(1, round(h))))
    mask = (np.asarray(region.getchannel("A")) >= 128).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    grid = cv2.resize(mask.astype(np.float32), (cols, rows), interpolation=cv2.INTER_AREA)
    return np.clip(grid, 0.0, 1.0)


def _positions(limit: int, ideal: float | None = None) -> list[int]:
    """0 ~ limit 를 GRID 칸으로 나눈 위치. 끝값과 가운데를 항상 넣고 중복은 없앤다.

    ideal 이 있으면 그 자리(0 ~ limit 로 자름)도 넣는다 — 격자가 성겨서 따라가기가 어긋나지 않게.
    """
    if limit <= 0:
        return [0]
    pos = [round(limit * i / (GRID - 1)) for i in range(GRID)]
    pos.append(limit // 2)
    if ideal is not None:
        pos.append(min(limit, max(0, round(ideal))))
    return sorted(set(pos))


def _size(base: tuple[int, int, int, int], z: float) -> tuple[int, int]:
    """가운데 크롭 크기를 z 배 확대한 크롭 크기."""
    if z == 1.0:
        return base[2], base[3]
    return max(1, round(base[2] / z)), max(1, round(base[3] / z))


def _upscale_ok(slot_h: float, ch: int) -> bool:
    return slot_h / ch <= MAX_UPSCALE


def home_zoom(pw: int, ph: int, slot_w: float, slot_h: float) -> float:
    """기본 구도 배율: BASE_ZOOM. 그 배율이 MAX_UPSCALE 을 넘으면 넘지 않는 가장 큰 배율 (0.01 단위, 최소 1.0)."""
    base = cover_crop(pw, ph, slot_w, slot_h)
    z = BASE_ZOOM
    while z > 1.0 and not _upscale_ok(slot_h, _size(base, z)[1]):
        z = round(z - 0.01, 2)
    return max(1.0, z)


def centered_crop(pw: int, ph: int, ratio: float, zoom: float) -> tuple[int, int, int, int]:
    """비율 ratio(w/h) 의 가운데 크롭을 zoom 배 확대해 가운데에 둔 영역. zoom=1 이면 cover_crop 과 같다."""
    cw, ch = _size(cover_crop(pw, ph, ratio, 1.0), zoom)
    return (pw - cw) // 2, (ph - ch) // 2, cw, ch


def home_crop(pw: int, ph: int, slot_w: float, slot_h: float) -> tuple[int, int, int, int]:
    """기본 구도 (x, y, w, h): 슬롯 비율의 가운데 크롭을 home_zoom 배 확대해 가운데에 둔 것."""
    cw, ch = _size(cover_crop(pw, ph, slot_w, slot_h), home_zoom(pw, ph, slot_w, slot_h))
    return (pw - cw) // 2, (ph - ch) // 2, cw, ch


def usable_faces(faces: list[FaceObs]) -> list[FaceObs]:
    """구도에 쓸 얼굴: 가장 큰 얼굴 높이의 SMALL_FACE_RATIO 미만인 얼굴(뒤쪽 행인)은 뺀다.
    기준 높이는 얼굴 모델이 찾은 얼굴(eye_open 이 있는 것)로 잡는다 — 사람 찾기로 추정한 머리는 팔을 벌리면
    크게 잡혀, 그것을 기준으로 삼으면 진짜 손님이 행인으로 빠진다. 추정 머리뿐이면 전부를 기준으로 한다."""
    if not faces:
        return []
    ref = [f for f in faces if f.eye_open is not None] or faces
    tallest = max(f.box[3] - f.box[1] for f in ref)
    return [f for f in faces if f.box[3] - f.box[1] >= SMALL_FACE_RATIO * tallest]


def _inside(crop: tuple[int, int, int, int], pw: int, ph: int, faces: list[FaceObs]) -> bool:
    """모든 얼굴(여백 FACE_PAD 포함)이 크롭 안인가."""
    cx, cy, cw, ch = crop
    for f in faces:
        x0, y0, x1, y1 = _padded(f.box)
        if x0 * pw < cx - 1e-6 or y0 * ph < cy - 1e-6 or x1 * pw > cx + cw + 1e-6 or y1 * ph > cy + ch + 1e-6:
            return False
    return True


def _fill_ratio(crop, pw: int, ph: int, faces: list[FaceObs]) -> float:
    """얼굴 전체 박스가 크롭에서 차지하는 비율 (가로 · 세로 중 큰 쪽, _cost 와 같은 식)."""
    ux0 = min(max(0.0, f.box[0]) for f in faces) * pw
    uy0 = min(max(0.0, f.box[1]) for f in faces) * ph
    ux1 = max(min(1.0, f.box[2]) for f in faces) * pw
    uy1 = max(min(1.0, f.box[3]) for f in faces) * ph
    return max((ux1 - ux0) / crop[2], (uy1 - uy0) / crop[3])


def _fill(crop, pw: int, ph: int, faces: list[FaceObs]) -> float:
    """fill 비용 (0~1): 얼굴 전체 박스가 크롭에서 FILL_TARGET 보다 작은 정도."""
    return max(0.0, (FILL_TARGET - _fill_ratio(crop, pw, ph, faces)) / FILL_TARGET)


def _near_target(crop, ux: float, uy: float) -> bool:
    """얼굴 전체 중심 (ux, uy 픽셀) 이 크롭 안 TARGET 의 데드존(HOME_DEADBAND) 안인가."""
    cx, cy, cw, ch = crop
    return (abs((ux - cx) / cw - TARGET[0]) <= HOME_DEADBAND[0]
            and abs((uy - cy) / ch - TARGET[1]) <= HOME_DEADBAND[1])


def compute_crop(pw: int, ph: int, slot_w: float, slot_h: float, faces: list[FaceObs],
                 occlusion=None) -> Crop:
    """슬롯 비율 크롭 (x, y, w, h). occlusion 은 occlusion_grid 의 격자 (없으면 장식을 보지 않는다).

    1) 쓸 얼굴이 없으면 가장 넓게 — 1.0배 가운데 (cover_crop, no_face). 사람이 어디 있는지 모르니 자르지 않는다.
    2) 얼굴이 MAX_FACES 이상이면 잡히지 않은 사람이 더 있을 수 있어 배율 1.0 에서 위치만 고른다.
    기본보다 더 확대하는 후보는 기본 구도에서 얼굴 전체 박스가 FAR_FILL 보다 작을 때(멀리 선 사람)만 본다 (3 · 4 · 5 공통).
    3) 모든 얼굴(여백 포함)이 기본 구도 안이고 얼굴 전체 중심이 TARGET 의 데드존(HOME_DEADBAND) 안이면 기본 구도 (home).
       멀리 선 사람이고, 더 확대하면 fill 이 나아지고 총비용이 MIN_GAIN 이상 낮아질 때만 기본보다 확대한다 (zoomed).
    4) 기본 구도 안이지만 데드존 밖이면 기본 배율로 따라가 얼굴을 가운데로 (follow, 화면 끝이면 갈 수 있는 데까지).
       멀리 선 사람이면 3) 과 같은 조건으로 따라간 구도보다 더 확대할 수 있다 (zoomed).
    5) 기본 구도 밖 얼굴이 있으면 배율 1.0 ~ 기본 배율 (멀리 선 사람이면 2.0 까지) · 위치 격자 중 비용이 가장 낮은 크롭.
    """
    base = cover_crop(pw, ph, slot_w, slot_h)
    hz = home_zoom(pw, ph, slot_w, slot_h)
    home = home_crop(pw, ph, slot_w, slot_h)
    used = usable_faces(faces)
    if not used:
        return Crop(*base, "no_face", True, 0.0)

    home_cost = _cost(home, pw, ph, hz, used, occlusion)[0]
    ux = (min(max(0.0, f.box[0]) for f in used) + max(min(1.0, f.box[2]) for f in used)) / 2 * pw
    uy = (min(max(0.0, f.box[1]) for f in used) + max(min(1.0, f.box[3]) for f in used)) / 2 * ph
    # 걸러 낸 뒤쪽 행인은 세지 않는다 — 검출기는 한도를 넘으면 큰 얼굴부터 남기므로, 한도 때문에 못 잡은 얼굴은
    # 이미 잡힌 작은 얼굴보다도 작다 (행인). 2026-11-21 행사에서 폭 1~2% 행인 셋 때문에 1.0배로 찍힌 컷이 있었다
    many = len(used) >= MAX_FACES
    inside = not many and _inside(home, pw, ph, used)
    # 기본 구도 안이어도 얼굴이 가운데(데드존)를 벗어나 있으면 같은 배율로 따라간다
    off = inside and not _near_target(home, ux, uy)
    # 기본보다 더 확대는 얼굴이 기본 구도에서도 아주 작을 때(멀리 선 사람)만 — 위치와 상관없이 같은 규칙.
    # 비율은 크기만 보므로 기본 구도의 자리와 상관없다. 덜 확대(widen)는 이 조건과 상관없다.
    far = _fill_ratio(home, pw, ph, used) < FAR_FILL
    if many:
        zooms: tuple[float, ...] = (1.0,)
    elif off:
        # 기본 배율로 따라가기 + (멀리 선 사람이면) 더 확대
        zooms = (hz,) + (tuple(z for z in ZOOMS if z > hz) if far else ())
    elif inside:
        # 기본 구도에 다 들어오고 가운데면 더 확대할 때만 움직인다
        zooms = tuple(z for z in ZOOMS if z > hz) if far else ()
    else:
        zooms = tuple(z for z in sorted(set(ZOOMS) | {hz}) if z <= hz or far)

    # 기본 구도는 그 배율이 후보에 있을 때만 출발점 (얼굴이 많아 1.0 만 쓰면 기본 구도도 버린다).
    # 데드존 밖(off)이면 기본 구도도 다른 자리와 똑같이 겨룬다 (출발점으로 우대하지 않는다)
    if (many and hz != 1.0) or off:
        best, best_cost, best_zoom = None, math.inf, 1.0
    else:
        best, best_cost, best_zoom = home, home_cost, hz
    skip_home = best is not None
    follow, follow_cost = None, math.inf   # off 일 때 기본 배율에서 가장 좋은 자리
    for z in zooms:
        cw, ch = _size(base, z)
        if z > 1.0 and not _upscale_ok(slot_h, ch):
            break  # 더 확대해도 계속 넘는다
        # 얼굴 전체 중심이 TARGET 에 오는 자리도 후보에 넣는다
        for y in _positions(ph - ch, uy - TARGET[1] * ch):
            for x in _positions(pw - cw, ux - TARGET[0] * cw):
                cand = (x, y, cw, ch)
                if cand == home and skip_home:
                    continue
                c = _cost(cand, pw, ph, z, used, occlusion)[0]
                if c < best_cost - 1e-12:
                    best, best_cost, best_zoom = cand, c, z
                if off and z == hz and c < follow_cost - 1e-12:
                    follow, follow_cost = cand, c

    if off:
        # 더 확대는 3) 과 같은 조건 (따라간 구도보다 fill 이 나아지고 총비용이 MIN_GAIN 이상 낮을 때)
        if (best_zoom > hz and follow_cost - best_cost >= MIN_GAIN
                and _fill(best, pw, ph, used) < _fill(follow, pw, ph, used)):
            return Crop(*best, "zoomed", False, best_cost)
        return Crop(*follow, "home" if follow == home else "follow", False, follow_cost)
    if inside:
        if (best == home or home_cost - best_cost < MIN_GAIN
                or _fill(best, pw, ph, used) >= _fill(home, pw, ph, used)):
            return Crop(*home, "home", False, home_cost)
        return Crop(*best, "zoomed", False, best_cost)
    if best_zoom < hz:
        reason = "widen"
    elif best_zoom > hz:
        reason = "zoomed"
    else:
        reason = "home" if best == home else "follow"
    return Crop(*best, reason, False, best_cost)


class SmartCropper:
    """합성 · 축소판이 함께 쓰는 슬롯별 크롭 계산기.

    컷 번호는 slot["shot"], 얼굴은 session.cut_faces() 의 같은 자리 (cuts() 와 같은 순서),
    장식 가림 격자는 슬롯마다 한 번만 만든다.
    손님이 '찍은 그대로' 를 고른 컷(session.cut_choices() 가 as_shot)은 얼굴과 상관없이 기본 구도 (reason="as_shot").
    얼굴 정보가 없거나 계산이 실패하면 가장 넓게 — 1.0배 가운데 (cover_crop, reason="unavailable").
    사람이 어디 있는지 모를 때 1.3배 가운데로 자르면 가장자리에 선 사람이 잘린다 (확인 지점 3).
    그것마저 못 구하면 None (compose 가 가운데 크롭) — 어떤 경우에도 촬영을 멈추지 않는다.
    """

    def __init__(self, frame_png: Image.Image, slots: list[dict], session):
        self.frame_png = frame_png
        self.slots = slots
        self.session = session
        self._grids: dict[tuple, np.ndarray] = {}

    def _grid(self, slot: dict) -> np.ndarray:
        key = (slot["cx"], slot["cy"], slot["w"], slot["h"], slot.get("rot", 0))
        grid = self._grids.get(key)
        if grid is None:
            grid = self._grids[key] = occlusion_grid(self.frame_png, slot)
        return grid

    def crop(self, slot: dict, cut: Image.Image) -> Crop | None:
        """슬롯 하나의 Crop. 찍은 그대로면 기본 구도, 얼굴 정보 없음 · 실패면 가장 넓게(cover_crop), 그것도 실패면 None."""
        return self._crop(slot, cut, lambda: self._as_shot(slot["shot"]),
                          lambda: self.session.cut_faces()[slot["shot"]])

    def shot_crop(self, slot: dict, cut: Image.Image, i: int) -> Crop | None:
        """사진 번호 i (session.shots 자리) 를 slot 모양으로 자른 Crop — 선택 · 얼굴도 사진 번호 자리의 것.

        더 찍고 고르기(extra 모드)는 슬롯이 정해지기 전이라 crop() (컷 번호 = 고른 순서) 을 쓸 수 없다.
        고르기 화면 · 축소판이 대표 슬롯 모양으로 미리 보여 줄 때 쓴다. 규칙은 crop() 과 같다."""
        def faces():
            shot_faces = getattr(self.session, "shot_faces", [])
            return shot_faces[i] if 0 <= i < len(shot_faces) else None

        return self._crop(slot, cut, lambda: self._shot_as_shot(i), faces)

    def _crop(self, slot: dict, cut: Image.Image, as_shot, faces_of) -> Crop | None:
        try:
            if as_shot():
                return Crop(*home_crop(cut.width, cut.height, slot["w"], slot["h"]), "as_shot", False, 0.0)
        except Exception as e:
            log.warning("찍은 그대로 크롭 계산 실패 — 가장 넓게(1.0배 가운데) 씁니다: %s", e)
            return self._widest(slot, cut)
        try:
            faces = faces_of()
            if faces is not None:
                return compute_crop(cut.width, cut.height, slot["w"], slot["h"], faces, self._grid(slot))
        except Exception as e:
            log.warning("스마트 크롭 계산 실패 — 가장 넓게(1.0배 가운데) 씁니다: %s", e)
        return self._widest(slot, cut)

    def _shot_as_shot(self, i: int) -> bool:
        """사진 번호 i 가 '찍은 그대로' 인가. 선택 정보가 없으면 아니다."""
        choice = getattr(self.session, "shot_choice", [])
        return 0 <= i < len(choice) and choice[i] == "as_shot"

    def _as_shot(self, shot: int) -> bool:
        """컷 shot 이 '찍은 그대로' 인가. 선택 정보가 없는 세션 · 고르기 전이면 아니다."""
        choices = getattr(self.session, "cut_choices", None)
        if choices is None:
            return False
        try:
            return choices()[shot] == "as_shot"
        except (ValueError, IndexError):
            return False

    def _widest(self, slot: dict, cut: Image.Image) -> Crop | None:
        """가장 넓게(1.0배 가운데, reason=unavailable). 그것도 못 구하면 None."""
        try:
            return Crop(*cover_crop(cut.width, cut.height, slot["w"], slot["h"]), "unavailable", True, 0.0)
        except Exception as e:
            log.warning("가장 넓은 크롭도 구하지 못해 compose 의 가운데 크롭을 씁니다: %s", e)
            return None

    def crop_for(self, slot: dict, cut: Image.Image) -> tuple[int, int, int, int] | None:
        """compose(crop_for=...) 에 넘기는 형태 (x, y, w, h)."""
        c = self.crop(slot, cut)
        return None if c is None else (c.x, c.y, c.w, c.h)

    def shot_crop_for(self, slot: dict, cut: Image.Image, i: int) -> tuple[int, int, int, int] | None:
        """shot_crop() 의 (x, y, w, h)."""
        c = self.shot_crop(slot, cut, i)
        return None if c is None else (c.x, c.y, c.w, c.h)
