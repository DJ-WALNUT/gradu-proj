"""버스트 분석기 — 별도 스레드에서 얼굴 모델로 프레임을 평가하고 베스트 한 장을 고른다.

- 촬영 장면이 쓰는 FaceDetector(app.detector)와 공유하지 않는 별도 FaceLandmarker 를 쓴다
  (IMAGE 모드, 블렌드셰이프 · 변환 행렬 출력).
- 작업 스레드는 하나다. 모델 불러오기 · 추론 · 닫기가 모두 그 스레드에서 일어난다.
- 분석 실패가 촬영을 멈추면 안 된다. 프레임 하나의 오류는 '얼굴 없음' 후보로 바꾸고,
  그 밖의 예외는 Future 에 실려 호출한 쪽이 처리한다.
- 입력 프레임은 읽기만 한다 (쓰지 않는다).
- 검출 전략(DETECT_MODE): 광각 · 단체에서 작은 얼굴을 놓치지 않도록 전체 프레임과 겹치는 좌우 반쪽을
  따로 검출해 합친다. 조각의 랜드마크는 전체 프레임 정규화 좌표로 되돌린 뒤 박스 · 눈 뜸을 계산하므로
  FaceObs.box 는 언제나 전체 프레임 기준이다 (거울은 그 뒤에 적용).
- 모든 후보를 검출한 뒤, 후보 여럿에서 꾸준히 잡히지 않은 얼굴(배경 물건 오검출 · 자꾸 놓치는 사람)은 고르기의
  얼굴 수 세기에서만 뺀다 (stable_faces). 구도에는 고른 프레임에서 잡힌 얼굴을 꾸준하지 않은 것까지 모두 쓴다 —
  진짜 사람을 자르는 것이 사진이 조금 넓어지는 것보다 나쁘다 (framing_faces). 고른 프레임에서 놓쳤어도 다른 후보
  2장 이상에서 같은 자리에 잡힌 얼굴은 구도에 더한다 (FRAMING_MIN_OTHERS). 고른 프레임에 얼굴이 없으면 시각이
  가장 가까운 다른 후보의 (꾸준한) 얼굴을 구도용으로 빌린다 (borrow_faces).
  모두 tools/eval_capture.py 가 그대로 불러 쓴다 (4조건 비교가 부스와 같은 동작이 되게).
- 사람 찾기 (Task H): 손으로 입을 가리거나 옆모습 · 멀리 서서 얼굴이 작으면 얼굴 모델이 놓친다. 셔터에 가장 가까운
  프레임 한 장에서 사람 검출기(EfficientDet-Lite0 'person')를 한 번 돌려, 얼굴 박스 가운데가 들어 있지 않은 사람마다
  추정 머리 박스를 구도용 얼굴에 더한다 (person_heads). 얼굴이 하나도 없으면 사람 박스가 곧 구도가 된다.
  모델 파일이 없거나 불러오기 · 검출에 실패하면 사람 찾기만 끄고 분석은 그대로 한다.
- 사람별 얼굴 다시 찾기 (Task K): 같은 사람 박스로, 얼굴이 없거나 작은 사람의 머리 둘레만 잘라 모든 후보에서 얼굴 모델을
  다시 돌린다 (_refine). 멀리 선 사람의 얼굴을 찾고 눈 뜸 값을 바로잡아 프레임 선택에 쓴다 — 조각 검출만으로는 작은
  얼굴의 뜬 눈이 감음으로 나와 후보가 모두 탈락했다. 사람 찾기가 꺼져 있으면 (구도 보정 꺼짐) 돌지 않는다.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np

from .burst import TimedFrame
from .quality import (Candidate, FaceObs, _min_metric, eye_open_from, frontality_from,
                      select_best, sharpness)

log = logging.getLogger(__name__)

INFER_LONG_SIDE = 640  # 추론용 사본의 긴 변

# 검출 전략. 광각 카메라에서 단체로 서면 얼굴이 작아(폭 10% 안팎) 전체 프레임 한 번으로는 놓친다
# (검출기가 그림 전체를 작은 정사각 입력으로 줄이고, 16:9 는 위아래 여백까지 생긴다).
#   "full"        : 전체 프레임 한 번 (예전 방식)
#   "halves"      : 높이 전체를 쓰는 겹치는 좌 · 우 두 조각
#   "full+halves" : 전체 + 두 조각 (가까이 선 큰 얼굴이 이음매에 걸려도 전체 검출이 잡는다)
# 단체에서 일부만 잡히면 구도 보정이 나머지를 자르므로 0개일 때만이 아니라 항상 조각도 돈다.
# tools/compare_detect.py 결과를 보고 바꿀 수 있게 상수 하나로 둔다.
DETECT_MODE = "full+halves"
DETECT_MODES = ("full", "halves", "full+halves")
HALF_FRAC = 0.65    # 조각 폭 (프레임 폭 대비). 왼쪽 [0, 0.65w) · 오른쪽 [0.35w, w) — 30% 겹침
DEDUPE_IOU = 0.3    # 박스 IoU 가 이보다 크면 같은 얼굴

# 꾸준히 잡힌 얼굴만 사람으로 (확인 지점 3). 배경 물건이 후보 10장 중 5장에서만 얼굴로 잡혀 얼굴 수가 2 · 1 로
# 깜빡이면 '얼굴 수 부족' 탈락이 겹치고 크롭이 그쪽으로 끌려간다.
STABLE_IOU = 0.3       # 다른 후보의 얼굴과 박스 IoU 가 이보다 크면 같은 자리 (사람은 1초 안에 크게 움직이지 않는다)
STABLE_RATIO = 0.6     # 얼굴이 잡힌 후보 수의 이 비율 미만에서만 잡힌 얼굴은 뺀다. 실제 오검출은 10장 중 5장(0.5),
                       # 잠깐 가려진 진짜 사람은 대개 10장 중 7~8장 이상이라 그 사이. 높이면 움직이는 사람을 잃는다
STABLE_MIN_CANDS = 3   # 후보가 이보다 적으면 거르지 않는다 (smart_crop 만 켠 한 장 분석 · 두 장으로는 비율이 무의미)
FRAMING_MIN_OTHERS = 2  # 고른 프레임에 없는 얼굴이 다른 후보 이만큼 이상에서 같은 자리(IoU > STABLE_IOU)에 잡혔으면 구도에 더한다.
                        # 한 장에서만 잡힌 것은 순간 오검출로 보고 더하지 않는다


# 사람 찾기 (구도용). 모델은 MediaPipe Tasks ObjectDetector, efficientdet_lite0.tflite (walnut/model_files.py)
PERSON_MODEL = "efficientdet_lite0.tflite"
PERSON_SCORE = 0.4       # 사람 점수 기준. 합성 사진 슬롯 52칸 시험에서 얼굴 모델이 놓친 11칸을 모두 찾았다
# 사람 박스 → 머리 박스 추정. data-dev 슬롯 조각 63쌍(얼굴 · 사람 둘 다 잡힌 칸)으로 보정했다:
# 얼굴 박스 대비 추정 박스 폭 1.23배 · 높이 1.38배(중앙값), 얼굴 박스를 덮는 비율 중앙값 0.998.
# 조금 크게 잡는다 — 크면 사진이 조금 넓어질 뿐이고, 작으면 머리가 잘린다.
HEAD_W_RATIO = 0.4       # 머리 폭 = 사람 박스 폭 × 이 값 (실측 얼굴 폭/사람 폭 중앙값 0.32)
HEAD_ASPECT = 1.2        # 머리 높이 = 머리 폭 × 이 값 (실측 얼굴 높이/폭 중앙값 1.05)
HEAD_TOP_PAD = 0.3       # 머리 위 = 사람 박스 위 + 머리 폭 × 이 값. 사람 박스 높이가 아니라 머리 폭 기준이다 —
                         # 가까이 선 사람은 사람 박스 아래가 프레임 끝에서 잘려 높이가 들쭉날쭉하다
                         # (실측 (얼굴 위 - 사람 위)/얼굴 폭 중앙값 0.52 — 얼굴 박스는 이마부터, 사람 박스는 머리카락부터)
PERSON_FACE_TOP = 0.6    # 얼굴 박스 가운데가 사람 박스 안(세로는 위쪽 이 비율 안)에 있으면 그 사람의 얼굴로 본다

# 사람별 얼굴 다시 찾기 (Task K). 멀리 선 사람은 조각 검출로는 얼굴이 아예 안 잡히거나, 잡혀도 눈 뜸 값이 낮게 나온다
# (2026-11-17 녹화 9개: 얼굴 폭 7~11% 에서 뜬 눈이 0.4~0.7, 폭 6% 는 10장 모두 못 찾음). 머리 둘레만 잘라 넣으면
# 얼굴이 입력을 채워 폭 6% 도 10장 모두 찾고 뜬 눈 0.75~0.92 · 감은 눈 0.23~0.46 으로 갈린다 (사람 하나 · 프레임 하나에 약 17ms).
REFINE_FACE_W = 0.18     # 얼굴 폭(프레임 폭 대비)이 이보다 작거나 얼굴이 없는 사람만 다시 찾는다. 가까운 큰 얼굴(폭 22%)은
                         # 조각 검출 값이 이미 맞다 (감은 눈 0.45~0.57, 뜬 눈 0.82~0.94)
REFINE_PAD = 1.0         # 추정 머리 박스 사방으로 머리 폭의 이 배수만큼 넓혀 자른다 (1초 사이 움직임 · 추정 오차 여유)
REFINE_MIN_PX = 48       # 자른 조각의 짧은 변이 이보다 작으면 다시 찾지 않는다 (얼굴이 될 수 없는 크기)
REFINE_BUDGET_SEC = 0.5  # 한 컷에서 다시 찾기에 쓰는 시간 상한. 넘길 것 같으면 남은 사람은 조각 검출 값 그대로 둔다
                         # (얼굴 없는 사람 → 얼굴이 작은 사람 순으로 먼저 한다)
REFINE_DEADLINE_SEC = 1.5  # 분석을 시작한 지 이만큼 지났으면 (다음 사람을 하면 넘길 것 같으면) 다시 찾기를 더 하지 않는다 —
                           # 촬영 장면의 ANALYZE_TIMEOUT(2.0초)에 걸리면 그 컷은 베스트 컷 없이 기준 프레임이 된다.
                           # 실측(개발 PC, 1080p): 두 사람 전체 0.8~1.25초 (조각 검출 0.45~0.83 + 사람 찾기 0.07 + 다시 찾기 0.33~0.50).
                           # 1.2 로 두었을 때는 조각 검출이 0.83초 걸린 컷에서 두 번째 사람을 못 해 후보가 모두 탈락했다


def head_box(person: tuple[float, float, float, float], w: int, h: int) -> tuple[float, float, float, float]:
    """사람 박스(정규화 x0 y0 x1 y1) → 추정 머리 박스(정규화). 프레임 밖은 자른다. w · h 는 프레임 화소."""
    x0, y0, x1, _ = person
    hw = (x1 - x0) * w * HEAD_W_RATIO
    hh = hw * HEAD_ASPECT
    cx = (x0 + x1) / 2 * w
    top = y0 * h + HEAD_TOP_PAD * hw
    c = lambda v: max(0.0, min(1.0, float(v)))  # noqa: E731
    return (c((cx - hw / 2) / w), c(top / h), c((cx + hw / 2) / w), c((top + hh) / h))


def person_heads(persons: list[tuple[float, float, float, float]], faces: list[FaceObs],
                 w: int, h: int) -> list[FaceObs]:
    """얼굴 박스 가운데가 하나도 들어 있지 않은 사람마다 추정 머리 (눈 뜸 · 방향 None). 좌표는 모두 원본(거울 전).

    '들어 있다' 는 가로는 사람 박스 안, 세로는 사람 박스 위쪽 PERSON_FACE_TOP 안이다. 얼굴이 없으면 모든 사람이 더해진다.
    """
    return [FaceObs(head_box(p, w, h), None, None) for p in persons if not _own_faces(p, faces)]


def _own_faces(person: tuple[float, float, float, float], faces: list[FaceObs]) -> list[FaceObs]:
    """그 사람의 얼굴로 볼 얼굴들 — 박스 가운데가 가로는 사람 박스 안, 세로는 위쪽 PERSON_FACE_TOP 안."""
    bottom = person[1] + PERSON_FACE_TOP * (person[3] - person[1])
    return [f for f in faces
            if person[0] <= (f.box[0] + f.box[2]) / 2 <= person[2] and person[1] <= (f.box[1] + f.box[3]) / 2 <= bottom]


def refine_regions(persons: list[tuple[float, float, float, float]], faces: list[FaceObs],
                   w: int, h: int) -> list[tuple[int, int, int, int]]:
    """얼굴을 다시 찾을 조각들 (화소 x0 y0 x1 y1). 얼굴이 없거나 작은(REFINE_FACE_W 미만) 사람의 머리 둘레다.

    순서는 얼굴 없는 사람 → 얼굴이 작은 사람 (같으면 왼쪽부터) — 시간이 모자라면 앞에서부터만 한다.
    persons · faces 는 같은 프레임의 정규화 좌표 (거울 전).
    """
    jobs = []
    for p in persons:
        fw = max((f.box[2] - f.box[0] for f in _own_faces(p, faces)), default=0.0)
        if fw >= REFINE_FACE_W:
            continue
        hb = head_box(p, w, h)
        pad = REFINE_PAD * (hb[2] - hb[0]) * w
        x0, x1 = int(max(0, np.floor(hb[0] * w - pad))), int(min(w, np.ceil(hb[2] * w + pad)))
        y0, y1 = int(max(0, np.floor(hb[1] * h - pad))), int(min(h, np.ceil(hb[3] * h + pad)))
        if min(x1 - x0, y1 - y0) < REFINE_MIN_PX:
            continue
        jobs.append((fw, p[0], (x0, y0, x1, y1)))
    jobs.sort(key=lambda j: (j[0], j[1]))
    return [j[2] for j in jobs]


def merge_refined(tile_faces: list[FaceObs], refined: list[tuple[float, FaceObs]], max_faces: int) -> list[FaceObs]:
    """조각 검출 얼굴에 다시 찾은 얼굴을 합친다. refined 는 [(조각 가운데까지 거리, 얼굴)].

    다시 찾은 쪽을 믿는다 (얼굴이 크게 들어가 눈 뜸 값이 맞다) — 같은 자리(IoU > DEDUPE_IOU)의 조각 검출 얼굴은 버린다.
    한 얼굴이 두 사람의 조각에서 다 잡혔으면 조각 가운데에 가까운 쪽(그 사람 자신의 조각)을 남긴다.
    다시 찾은 것이 없으면 tile_faces 를 그대로 돌려준다. max_faces 를 넘으면 큰 얼굴부터, 결과는 박스 왼쪽 x 순.
    """
    if not refined:
        return tile_faces
    kept: list[FaceObs] = []
    for _, f in sorted(refined, key=lambda r: r[0]):
        if all(_iou(f.box, k.box) <= DEDUPE_IOU for k in kept):
            kept.append(f)
    for f in tile_faces:
        if all(_iou(f.box, k.box) <= DEDUPE_IOU for k in kept):
            kept.append(f)
    area = lambda f: (f.box[2] - f.box[0]) * (f.box[3] - f.box[1])  # noqa: E731
    kept = sorted(kept, key=lambda f: -area(f))[:max(0, max_faces)]
    return sorted(kept, key=lambda f: f.box)


@dataclass
class BurstResult:
    raw: np.ndarray          # 고른 프레임, 거울 적용 전 그대로 (거울은 촬영 경로가 따로 적용한다)
    faces: list[FaceObs]     # 거울을 적용한 뒤의 좌표
    info: dict               # JSON 으로 쓸 수 있는 값만 (이미지 없음)


def _face_box(landmarks) -> tuple[float, float, float, float]:
    xs = [p.x for p in landmarks]
    ys = [p.y for p in landmarks]
    c = lambda v: max(0.0, min(1.0, float(v)))  # noqa: E731
    return (c(min(xs)), c(min(ys)), c(max(xs)), c(max(ys)))


def detect_tiles(w: int, mode: str) -> list[tuple[str, int, int]]:
    """전략의 조각 목록 [(이름, x 시작, x 끝)]. 순서는 full → left → right (중복 제거 때 먼저 나온 쪽)."""
    if mode not in DETECT_MODES:
        log.warning("알 수 없는 검출 전략 %r — 전체 프레임 한 번으로 검출합니다", mode)
        mode = "full"
    tiles = []
    if mode in ("full", "full+halves"):
        tiles.append(("full", 0, w))
    if mode in ("halves", "full+halves"):
        tw = round(w * HALF_FRAC)
        tiles.append(("left", 0, tw))
        tiles.append(("right", w - tw, w))
    return tiles


def _map_landmarks(landmarks, ox: int, tw: int, w: int) -> list:
    """조각 정규화 좌표 → 전체 프레임 정규화 좌표. 조각은 높이를 다 쓰므로 y 는 그대로."""
    return [SimpleNamespace(x=(p.x * tw + ox) / w, y=p.y) for p in landmarks]


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    area = lambda r: max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])  # noqa: E731
    return inter / (area(a) + area(b) - inter)


def _merge_faces(faces: list[FaceObs], max_faces: int) -> list[FaceObs]:
    """조각들에서 나온 얼굴을 합친다 (faces 는 full → left → right, 조각 안에서는 검출 순서).

    IoU > DEDUPE_IOU 이면 같은 얼굴 — 박스가 더 큰 쪽(더 온전한 쪽)을, 같으면 먼저 나온 쪽을 남긴다.
    max_faces 를 넘으면 큰 얼굴부터 남기고, 결과는 박스 왼쪽 x 순 (같은 입력이면 같은 결과).
    """
    area = lambda f: (f.box[2] - f.box[0]) * (f.box[3] - f.box[1])  # noqa: E731
    order = sorted(range(len(faces)), key=lambda i: (-area(faces[i]), i))
    kept: list[FaceObs] = []
    for i in order:
        if all(_iou(faces[i].box, k.box) <= DEDUPE_IOU for k in kept):
            kept.append(faces[i])
    kept = kept[:max(0, max_faces)]
    return sorted(kept, key=lambda f: f.box)


def stable_faces(cands: list[Candidate], resharpen=None) -> tuple[list[Candidate], int]:
    """꾸준히 잡힌 얼굴만 남긴 새 후보 목록과 뺀 얼굴 수 (후보마다 센 합).

    후보마다 각 얼굴이 몇 후보(자기 포함)에서 같은 자리(IoU > STABLE_IOU)에 잡혔는지 세어, 얼굴이 하나라도 잡힌
    후보 수의 STABLE_RATIO 미만이면 뺀다. 후보가 STABLE_MIN_CANDS 보다 적으면 그대로 돌려준다.
    입력은 고치지 않는다. 얼굴이 빠진 후보는 resharpen(번호, 남은 얼굴) 이 있으면 선명도를 다시 잰다
    (_observe 와 같이 남은 얼굴 영역의 최솟값 — 가짜 얼굴의 흐림이 탈락을 만들지 않게).
    """
    if len(cands) < STABLE_MIN_CANDS:
        return list(cands), 0
    with_faces = sum(1 for c in cands if c.faces)
    need = STABLE_RATIO * with_faces
    out, dropped = [], 0
    for i, c in enumerate(cands):
        keep = [f for f in c.faces
                if sum(1 for o in cands if any(_iou(f.box, g.box) > STABLE_IOU for g in o.faces)) >= need - 1e-9]
        if len(keep) == len(c.faces):
            out.append(c)
            continue
        dropped += len(c.faces) - len(keep)
        sharp = c.sharpness if resharpen is None else float(resharpen(i, keep))
        out.append(Candidate(c.t, sharp, keep))
    return out, dropped


def borrow_faces(cands: list[Candidate], index: int) -> tuple[list[FaceObs], int | None]:
    """구도에 쓸 얼굴과 빌려 온 후보 번호 (빌리지 않았으면 None).

    고른 후보에 얼굴이 없고 다른 후보에 있으면, 시각이 가장 가까운 후보(같으면 앞 번호)의 얼굴을 쓴다.
    프레임 선택 · 점수에는 쓰지 않는다. 지금 select_best 는 얼굴이 가장 많은 후보 중에서 고르므로
    보통은 빌릴 일이 없다 — 고르는 규칙이 바뀌어도 사람이 잘리지 않게 두는 안전장치다.
    """
    faces = cands[index].faces
    if faces:
        return faces, None
    others = [j for j, c in enumerate(cands) if c.faces and j != index]
    if not others:
        return faces, None
    j = min(others, key=lambda k: (abs(cands[k].t - cands[index].t), k))
    return cands[j].faces, j


def framing_faces(raw: list[Candidate], kept: list[Candidate],
                  index: int) -> tuple[list[FaceObs], int | None, list[int], int]:
    """고른 프레임의 구도용 얼굴, 빌려 온 후보 번호, 그중 꾸준하지 않은 얼굴의 번호, 다른 후보에서 더한 얼굴 수.

    raw 는 거르기 전 후보, kept 는 stable_faces 를 거친 후보 (같은 순서). 진짜 사람을 자르는 것이 사진이 조금
    넓어지는 것보다 나쁘다는 결정을 따른다.
    1) 고른 프레임에 잡힌 얼굴이 있으면 꾸준하지 않은 얼굴까지 모두 쓴다. 없으면 borrow_faces(kept, index).
    2) 위 얼굴 어느 것과도 같은 자리(IoU > STABLE_IOU)가 아닌 얼굴이 다른 후보 FRAMING_MIN_OTHERS 장 이상에서
       잡혔으면 더한다 (고른 프레임에서만 놓친 사람). 박스는 시각이 고른 프레임에 가장 가까운 후보(같으면 앞 번호)의 것.
    결과 순서는 1) 의 얼굴 → 더한 얼굴 (더한 것은 가까운 후보 순).
    """
    faces = list(raw[index].faces)
    src: int | None = None
    unstable: list[int] = []
    if faces:
        stable = kept[index].faces
        unstable = [k for k, f in enumerate(faces) if not any(f is g for g in stable)]
    else:
        borrowed, src = borrow_faces(kept, index)
        faces = list(borrowed)
    others = sorted((j for j in range(len(raw)) if j != index),
                    key=lambda j: (abs(raw[j].t - raw[index].t), j))
    added = 0
    for j in others:
        for g in raw[j].faces:
            if any(_iou(g.box, f.box) > STABLE_IOU for f in faces):
                continue
            seen = sum(1 for k in others if any(_iou(g.box, h.box) > STABLE_IOU for h in raw[k].faces))
            if seen >= FRAMING_MIN_OTHERS:
                faces.append(g)
                added += 1
    return faces, src, unstable, added


def _mirror_box(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return (1.0 - box[2], box[1], 1.0 - box[0], box[3])


class BurstAnalyzer:
    def __init__(self, model_path: Path, max_faces: int = 4, landmarker=None, detect_mode: str | None = None,
                 person_detector=None, person_model_path: Path | None = None, person_enabled: bool = True):
        self.model_path = Path(model_path)
        self.max_faces = max_faces
        self.detect_mode = detect_mode  # None 이면 부를 때마다 모듈 상수 DETECT_MODE
        self._landmarker = landmarker
        self._owns_landmarker = landmarker is None
        # 사람 찾기: 주입한 검출기가 없으면 얼굴 모델 옆의 파일을 작업 스레드에서 처음 쓸 때 불러온다
        self.person_model_path = (Path(person_model_path) if person_model_path
                                  else self.model_path.parent / PERSON_MODEL)
        self._person = person_detector
        self._owns_person = person_detector is None
        self._person_off = False   # 파일이 없거나 불러오지 못했으면 True — 경고는 그때 한 번
        # 구도 보정이 꺼져 있으면 머리를 더해도 쓸 곳이 없다 — 부르는 쪽(앱)이 알려 준다. 모델도 불러오지 않는다.
        # 기본 True 는 tools/eval_capture.py 처럼 구도를 늘 계산하는 쪽을 위한 것
        self.person_enabled = bool(person_enabled)
        self.available = landmarker is not None or self.model_path.is_file()
        if not self.available:
            log.warning("베스트 컷용 얼굴 모델이 없어 분석을 쓸 수 없습니다: %s (tools/download_models.py)",
                        self.model_path)
        self._closed = False
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="burst-analysis")

    # ---- 작업 스레드에서만 호출한다 ----
    def _ensure_loaded(self) -> None:
        if self._landmarker is not None or not self.available:
            return
        try:
            from mediapipe.tasks.python import BaseOptions, vision

            opts = vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(self.model_path)),
                running_mode=vision.RunningMode.IMAGE, num_faces=self.max_faces,
                output_face_blendshapes=True, output_facial_transformation_matrixes=True,
                min_face_detection_confidence=0.5)
            self._landmarker = vision.FaceLandmarker.create_from_options(opts)
        except Exception as exc:  # import 실패, 모델 손상 등
            log.error("베스트 컷용 얼굴 모델을 불러오지 못했습니다: %s", exc)
            self.available = False

    def _ensure_person(self) -> bool:
        """사람 검출기를 쓸 수 있으면 True. 처음 한 번만 불러오고, 실패하면 사람 찾기만 끈다 (경고 한 번)."""
        if self._person is not None:
            return True
        if self._person_off:
            return False
        if not self.person_model_path.is_file():
            log.warning("사람 찾기 모델이 없어 사람 찾기를 끕니다 (얼굴 분석은 그대로): %s (tools/download_models.py)",
                        self.person_model_path)
            self._person_off = True
            return False
        try:
            from mediapipe.tasks.python import BaseOptions, vision

            opts = vision.ObjectDetectorOptions(
                base_options=BaseOptions(model_asset_path=str(self.person_model_path)),
                running_mode=vision.RunningMode.IMAGE, category_allowlist=["person"],
                score_threshold=PERSON_SCORE, max_results=self.max_faces)
            self._person = vision.ObjectDetector.create_from_options(opts)
            return True
        except Exception as exc:  # import 실패, 모델 손상 등
            log.warning("사람 찾기 모델을 불러오지 못해 사람 찾기를 끕니다 (얼굴 분석은 그대로): %s", exc)
            self._person_off = True
            return False

    def _load_all(self) -> None:
        self._ensure_loaded()
        if self.available and self.person_enabled:
            self._ensure_person()

    def _persons(self, rgb: np.ndarray) -> list[tuple[float, float, float, float]]:
        """프레임 전체 한 번에서 사람 박스(정규화). 오류는 호출한 쪽이 처리한다."""
        import mediapipe as mp

        h, w = rgb.shape[:2]
        long_side = max(h, w)
        if long_side > INFER_LONG_SIDE:  # 검출기 입력은 320x320 이라 줄여도 결과가 거의 같고 변환이 빠르다
            s = INFER_LONG_SIDE / long_side
            rgb = cv2.resize(rgb, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
        ih, iw = rgb.shape[:2]
        res = self._person.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
        c = lambda v: max(0.0, min(1.0, float(v)))  # noqa: E731
        out = []
        for d in getattr(res, "detections", None) or []:
            cats = getattr(d, "categories", None) or []
            if cats and not any(getattr(k, "category_name", None) == "person" for k in cats):
                continue
            b = d.bounding_box
            box = (c(b.origin_x / iw), c(b.origin_y / ih), c((b.origin_x + b.width) / iw),
                   c((b.origin_y + b.height) / ih))
            if box[2] > box[0] and box[3] > box[1]:
                out.append(box)
        return out

    def _find_persons(self, rgb: np.ndarray) -> tuple[list[tuple[float, float, float, float]] | None, float | None]:
        """사람 박스(정규화)와 사람 찾기 ms. 꺼져 있거나 실패했으면 (None, None). 예외를 던지지 않는다."""
        if not self.person_enabled or not self._ensure_person():
            return None, None
        t0 = time.perf_counter()
        try:
            persons = self._persons(rgb)
        except Exception as exc:
            log.warning("사람 찾기에 실패해 얼굴만으로 구도를 잡습니다: %s", exc)
            return None, None
        return persons, (time.perf_counter() - t0) * 1000.0

    def _person_heads(self, rgb: np.ndarray, faces: list[FaceObs]) -> tuple[list[FaceObs], float | None]:
        """구도에 더할 추정 머리와 사람 찾기 ms (돌지 않았거나 실패했으면 None). 예외를 던지지 않는다."""
        persons, ms = self._find_persons(rgb)
        if persons is None:
            return [], None
        h, w = rgb.shape[:2]
        return person_heads(persons, faces, w, h), ms

    def _faces_in_rect(self, rgb: np.ndarray, rect: tuple[int, int, int, int]) -> list[tuple[float, FaceObs]]:
        """프레임의 조각 rect(화소 x0 y0 x1 y1)에서 얼굴을 찾는다 → [(조각 가운데까지 거리(화소), 얼굴)]. 좌표는 전체 프레임 기준."""
        h, w = rgb.shape[:2]
        x0, y0, x1, y1 = rect
        cw, ch = x1 - x0, y1 - y0
        res = self._detect(rgb[y0:y1, x0:x1])
        blends = list(getattr(res, "face_blendshapes", None) or [])
        mats = list(getattr(res, "facial_transformation_matrixes", None) or [])
        out = []
        for i, lm in enumerate(res.face_landmarks or []):
            lm = [SimpleNamespace(x=(p.x * cw + x0) / w, y=(p.y * ch + y0) / h) for p in lm]
            box = _face_box(lm)
            eye = eye_open_from(blends[i] if i < len(blends) else None, lm, w / h)
            pose = frontality_from(mats[i] if i < len(mats) else None)
            dist = float(np.hypot((box[0] + box[2]) / 2 * w - (x0 + x1) / 2, (box[1] + box[3]) / 2 * h - (y0 + y1) / 2))
            out.append((dist, FaceObs(box, eye, pose)))
        return out

    def _refine(self, rgbs: list[np.ndarray], faces: list[list[FaceObs]], persons, ref: int,
                deadline: float | None = None) -> tuple[list[list[FaceObs]], int]:
        """사람별 얼굴 다시 찾기 → (프레임별 얼굴, 다시 찾은 사람 수). 바뀌지 않은 프레임은 받은 목록 그대로 돌려준다.

        사람 위치는 ref 프레임 한 장의 것을 모든 프레임에 쓴다 (1초 사이라 머리 둘레 조각 안에 남는다).
        사람 하나를 모든 프레임에서 끝낸 뒤 다음 사람으로 간다 — 일부 프레임만 고치면 눈 뜸 값이 프레임끼리 어긋난다.
        다음 사람을 하면 REFINE_BUDGET_SEC 나 deadline(perf_counter 시각)을 넘길 것 같으면 거기서 멈춘다.
        조각 하나의 오류는 그 프레임만 건너뛴다.
        """
        h, w = rgbs[ref].shape[:2]
        found: list[list[tuple[float, FaceObs]]] = [[] for _ in rgbs]
        t0, last, done = time.perf_counter(), 0.0, 0
        for rect in refine_regions(persons, faces[ref], w, h):
            t1 = time.perf_counter()
            if (done and (t1 - t0) + last > REFINE_BUDGET_SEC) or (deadline is not None and t1 + last > deadline):
                log.info("얼굴 다시 찾기를 %d명에서 멈춥니다 (시간 상한)", done)
                break
            warned = False
            for i, rgb in enumerate(rgbs):
                if rgb.shape[:2] != (h, w):
                    continue
                try:
                    found[i].extend(self._faces_in_rect(rgb, rect))
                except Exception as exc:
                    if not warned:
                        log.warning("얼굴 다시 찾기 조각 하나를 건너뜁니다: %s", exc)
                        warned = True
            last = time.perf_counter() - t1
            done += 1
        return [merge_refined(fs, found[i], self.max_faces) for i, fs in enumerate(faces)], done

    def _close_landmarker(self) -> None:
        lm, self._landmarker = self._landmarker, None
        if lm is not None and self._owns_landmarker:
            try:
                lm.close()
            except Exception as exc:
                log.warning("얼굴 모델을 닫는 중 오류: %s", exc)
        pd, self._person = self._person, None
        if pd is not None and self._owns_person:
            try:
                pd.close()
            except Exception as exc:
                log.warning("사람 찾기 모델을 닫는 중 오류: %s", exc)

    def _detect(self, rgb: np.ndarray):
        import mediapipe as mp

        h, w = rgb.shape[:2]
        long_side = max(h, w)
        if long_side > INFER_LONG_SIDE:
            s = INFER_LONG_SIDE / long_side
            rgb = cv2.resize(rgb, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        return self._landmarker.detect(image)

    def _mode(self, mode: str | None = None) -> str:
        return mode or self.detect_mode or DETECT_MODE

    def _faces_in(self, rgb: np.ndarray, ox: int, tw: int, aspect: float) -> list[FaceObs]:
        """조각 rgb[:, ox:ox+tw] 에서 얼굴을 찾아 전체 프레임 정규화 좌표로 돌려준다."""
        h, w = rgb.shape[:2]
        whole = ox == 0 and tw == w
        res = self._detect(rgb if whole else rgb[:, ox:ox + tw])
        lms = list(res.face_landmarks or [])
        blends = list(getattr(res, "face_blendshapes", None) or [])
        mats = list(getattr(res, "facial_transformation_matrixes", None) or [])
        faces = []
        for i, lm in enumerate(lms):
            if not whole:
                lm = _map_landmarks(lm, ox, tw, w)
            # blendshape · 변환 행렬은 크기 · 이동과 무관해 조각에서 나온 그대로 쓴다
            eye = eye_open_from(blends[i] if i < len(blends) else None, lm, aspect)
            pose = frontality_from(mats[i] if i < len(mats) else None)
            faces.append(FaceObs(_face_box(lm), eye, pose))
        return faces

    def _observe(self, rgb: np.ndarray, gray: np.ndarray,
                 mode: str | None = None) -> tuple[float, list[FaceObs]]:
        """프레임 하나의 (선명도, 얼굴 목록). 오류는 호출한 쪽이 처리한다.

        조각이 여럿이면 실패한 조각만 버리고 나머지 결과를 쓴다. 모두 실패하면 마지막 예외를 던진다.
        """
        h, w = rgb.shape[:2]
        aspect = w / h
        tiles = detect_tiles(w, self._mode(mode))
        if len(tiles) == 1:
            _, x0, x1 = tiles[0]
            faces = self._faces_in(rgb, x0, x1 - x0, aspect)  # 조각 하나: 예전과 같은 결과 · 순서
        else:
            found, err, ok = [], None, False
            for name, x0, x1 in tiles:
                try:
                    found.extend(self._faces_in(rgb, x0, x1 - x0, aspect))
                    ok = True
                except Exception as exc:
                    log.warning("검출 조각 %s 를 분석하지 못해 건너뜁니다: %s", name, exc)
                    err = exc
            if not ok and err is not None:
                raise err
            faces = _merge_faces(found, self.max_faces)
        sharps = [sharpness(gray, f.box) for f in faces]  # 선명도는 전체 프레임 기준 박스로
        return (min(sharps) if sharps else sharpness(gray)), faces

    def _evaluate(self, tf: TimedFrame) -> Candidate:
        gray = cv2.cvtColor(tf.rgb, cv2.COLOR_RGB2GRAY)
        try:
            sharp, faces = self._observe(tf.rgb, gray)
        except Exception as exc:
            log.warning("프레임 하나를 분석하지 못해 얼굴 없음으로 처리합니다: %s", exc)
            sharp, faces = sharpness(gray), []
        return Candidate(tf.t, float(sharp), faces)

    def _analyze(self, frames: list[TimedFrame], shutter_t: float, mirror: bool) -> BurstResult:
        t_start = time.perf_counter()
        self._load_all()
        t_loaded = time.perf_counter()  # 처음 한 번의 모델 불러오기는 detect 에 넣지 않는다
        if not self.available:
            raise RuntimeError("얼굴 모델을 쓸 수 없어 분석하지 못했습니다")
        cands = [self._evaluate(f) for f in frames]

        def resharpen(i: int, faces: list[FaceObs]) -> float:
            gray = cv2.cvtColor(frames[i].rgb, cv2.COLOR_RGB2GRAY)
            sharps = [sharpness(gray, f.box) for f in faces]
            return min(sharps) if sharps else sharpness(gray)

        # 사람 찾기는 셔터에 가장 가까운 프레임 한 장에서 한 번 — 얼굴 다시 찾기와 구도용 머리가 함께 쓴다
        persons, person_ms, refined, refine_ms = None, None, 0, 0.0
        if frames:
            ref = min(range(len(frames)), key=lambda i: (abs(frames[i].t - shutter_t), i))
            persons, person_ms = self._find_persons(frames[ref].rgb)
        if persons:
            t_refine = time.perf_counter()
            new, refined = self._refine([f.rgb for f in frames], [c.faces for c in cands], persons, ref,
                                        deadline=t_loaded + REFINE_DEADLINE_SEC)
            cands = [c if fs is c.faces else Candidate(c.t, resharpen(i, fs), fs)
                     for i, (c, fs) in enumerate(zip(cands, new))]
            refine_ms = (time.perf_counter() - t_refine) * 1000.0

        raw = cands
        cands, unstable = stable_faces(raw, resharpen)  # 고르기용 (꾸준하지 않은 얼굴을 세지 않는다)
        t_detect = time.perf_counter()
        sel = select_best(cands, shutter_t)
        t_select = time.perf_counter()

        # 구도용: 고른 프레임의 얼굴 전부 (꾸준하지 않은 것 포함) — 거울은 그 뒤에 (지금과 같은 순서)
        faces, faces_from, faces_unstable, faces_added = framing_faces(raw, cands, sel.index)
        # 얼굴 모델이 끝내 놓친 사람: 얼굴 박스 없는 사람의 추정 머리를 더한다 (거울 전 좌표)
        heads = []
        if persons:
            h, w = frames[sel.index].rgb.shape[:2]
            heads = person_heads(persons, faces, w, h)
        faces = faces + heads
        if mirror:
            faces = [FaceObs(_mirror_box(f.box), f.eye_open, f.frontality) for f in faces]
        info = {
            "detect_mode": self._mode(),
            "reason": sel.reason,
            "fallback_used": bool(sel.fallback_used),
            "scores": [None if s is None else float(s) for s in sel.scores],
            "rejects": list(sel.rejects),
            "index": int(sel.index),
            "faces_from": None if faces_from is None else int(faces_from),
            "unstable_faces": int(unstable),
            "faces_unstable": [int(k) for k in faces_unstable],
            "faces_added": int(faces_added),
            "person_heads": len(heads),
            "person_ms": None if person_ms is None else float(person_ms),
            "refined": int(refined),            # 얼굴을 다시 찾은 사람 수
            "refine_ms": float(refine_ms),
            "candidates": [{
                "t": float(c.t),
                "sharpness": float(c.sharpness),
                "faces": len(c.faces),
                "eye": _opt(_min_metric([f.eye_open for f in c.faces])),
                "frontality": _opt(_min_metric([f.frontality for f in c.faces])),
            } for c in cands],
            "timings": {
                "load": (t_loaded - t_start) * 1000.0,
                "detect": (t_detect - t_loaded) * 1000.0,
                "select": (t_select - t_detect) * 1000.0,
                "person": float(person_ms or 0.0),   # detect 안에 들어 있다 (refine 도)
                "refine": float(refine_ms),
                "total": (time.perf_counter() - t_start) * 1000.0,
            },
        }
        return BurstResult(frames[sel.index].rgb, faces, info)

    def _detect_each(self, frames: list[np.ndarray], mode: str | None) -> list[tuple[list[FaceObs], float]]:
        out = []
        for rgb in frames:
            t0 = time.perf_counter()
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            try:
                _, faces = self._observe(rgb, gray, mode)
            except Exception as exc:
                log.warning("프레임 하나를 분석하지 못해 얼굴 없음으로 셉니다: %s", exc)
                faces = []
            out.append((faces, (time.perf_counter() - t0) * 1000.0))
        return out

    # ---- 호출하는 쪽 API ----
    def warm(self) -> None:
        """모델을 작업 스레드에서 미리 불러오도록 예약한다. 기다리지 않고, 실패해도 예외를 던지지 않는다."""
        with self._lock:
            if self._closed:
                return
            self._executor.submit(self._load_all)

    def submit(self, frames: list[TimedFrame], shutter_t: float, mirror: bool) -> Future:
        with self._lock:
            if self._closed:
                raise RuntimeError("분석기가 이미 닫혀 있어 새 분석을 맡길 수 없습니다")
            return self._executor.submit(self._analyze, list(frames), shutter_t, mirror)

    def detect_frames(self, frames: list[np.ndarray], mode: str | None = None) -> Future:
        """검출 비교용: 프레임(RGB)마다 (얼굴 목록, 분석 ms) 를 작업 스레드에서 구한다. 거울은 쓰지 않는다.

        ms 는 회색 변환 · 검출 · 선명도까지 프레임 하나에 든 시간이다. 프레임 하나의 오류는 얼굴 없음으로 센다.
        """
        def work():
            self._ensure_loaded()
            if not self.available:
                raise RuntimeError("얼굴 모델을 쓸 수 없어 분석하지 못했습니다")
            return self._detect_each(frames, mode)

        with self._lock:
            if self._closed:
                raise RuntimeError("분석기가 이미 닫혀 있어 새 분석을 맡길 수 없습니다")
            return self._executor.submit(work)

    def detect_burst(self, frames: list[np.ndarray], ref: int, mode: str | None = None) -> Future:
        """4조건 비교용: detect_frames 에 _analyze 와 같은 얼굴 다시 찾기까지 → Future[[(얼굴 목록, ms)]].

        ref 는 사람 찾기를 돌릴 프레임 번호 (부스는 셔터에 가장 가까운 프레임). 다시 찾기 시간은 프레임에 고르게 나눠 더한다.
        """
        def work():
            self._load_all()
            if not self.available:
                raise RuntimeError("얼굴 모델을 쓸 수 없어 분석하지 못했습니다")
            out = self._detect_each(frames, mode)
            if not frames:
                return out
            t0 = time.perf_counter()
            persons, _ = self._find_persons(frames[ref])
            if persons:
                new, _ = self._refine(list(frames), [fs for fs, _ in out], persons, ref)
                share = (time.perf_counter() - t0) * 1000.0 / len(frames)
                out = [(fs, ms + share) for fs, (_, ms) in zip(new, out)]
            return out

        with self._lock:
            if self._closed:
                raise RuntimeError("분석기가 이미 닫혀 있어 새 분석을 맡길 수 없습니다")
            return self._executor.submit(work)

    def person_heads_for(self, rgb: np.ndarray, faces: list[FaceObs]) -> Future:
        """구도 비교용: 원본 프레임(RGB) 한 장에서 _analyze 와 같은 사람 찾기 → Future[(추정 머리 목록, ms 또는 None)].

        tools/eval_capture.py 가 부스와 같은 구도용 얼굴을 만들 때 쓴다. faces · 결과 모두 거울 전 좌표다.
        """
        def work():
            self._load_all()
            return self._person_heads(rgb, list(faces))

        with self._lock:
            if self._closed:
                raise RuntimeError("분석기가 이미 닫혀 있어 새 분석을 맡길 수 없습니다")
            return self._executor.submit(work)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._executor.submit(self._close_landmarker)
            self._executor.shutdown(wait=False)


def _opt(v: float | None) -> float | None:
    return None if v is None else float(v)
