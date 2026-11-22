"""4조건 비교 평가 도구 — 같은 시퀀스를 네 조건으로 돌려 버스트 · 구도 보정의 효과를 수치로 비교한다.

    .\\.venv\\Scripts\\python tools\\eval_capture.py [--root eval_data] [--frame assets\\frame\\sticker_party.png]
        [--out <폴더>] [--seed N] [--reshuffle] [--debug]

조건 (시퀀스 하나 = 컷 하나로 보고, 프레임의 슬롯 각각에 그 컷을 넣는다):
  baseline  셔터에 가장 가까운 프레임 + 가운데 크롭 (1.0배) — 지금 행사 부스(플래그 끔)와 같다
  A         버스트만: select_best 로 고른 프레임 + 가운데 크롭
  B         구도 보정만: 셔터 프레임 + compute_crop (센터 스테이지)
  AB        둘 다: 고른 프레임 + compute_crop

얼굴은 시퀀스마다 모든 프레임을 'full+halves'(전체 + 좌우 반쪽)로 한 번 검출하고, 각 조건이 쓰는 프레임의
얼굴로 크롭 · 지표를 구한다. 버스트 조건(A · AB)은 부스와 똑같이 walnut.analysis 의 stable_faces(꾸준히 잡히지
않은 얼굴은 고르기에서만 빼기)와 framing_faces(구도에는 고른 프레임의 얼굴 전부 + 그 프레임만 놓친 얼굴 중 다른
후보 2장 이상에서 잡힌 것, 얼굴이 없으면 가장 가까운 후보의 얼굴을 빌리기)를 쓴다. 셔터 프레임 한 장만 쓰는 조건(baseline · B)은 부스의 smart_crop 만 켠 경우처럼 한 장 분석이라 둘 다 없다.
검출에는 부스처럼 사람별 얼굴 다시 찾기(BurstAnalyzer.detect_burst — 셔터 프레임의 사람 박스로 머리 둘레를 잘라 모든
프레임에서 다시 검출)가 들어 있어, 네 조건 모두 다시 찾은 얼굴 · 눈 뜸 값을 쓴다 (부스의 분석 시작 뒤 시간 제한은 없다).
구도 보정 조건(B · AB)은 부스처럼 셔터 프레임 한 장에서 사람 찾기(BurstAnalyzer.person_heads_for)를 돌려 얼굴
박스가 없는 사람의 추정 머리를 크롭용 얼굴에 더한다 (분석기에 그 기능이 없거나 모델이 없으면 얼굴만). 채점은 지금처럼
검출한 얼굴 기준이라, 얼굴이 하나도 없는 시퀀스는 사람 찾기로 크롭이 달라져도 얼굴 지표가 비어 채점할 수 없다.
거른 · 빌린 얼굴은 고르기 · 크롭에만 쓰고, 지표 · 눈 뜸은 네 조건 모두 그 프레임에서 검출한 얼굴 그대로(거르기 전)로
잰다 — 같은 얼굴 집합으로 채점해야 비교가 기울지 않는다 (거르기가 뺀 배경 물건도 모든 조건에 똑같이 셈한다). 지표는 구도에 쓰는 얼굴(framing.usable_faces — 가장 큰 얼굴 높이의 40% 미만인
뒤쪽 행인은 뺀다)의 여백 없는 박스로 잰다. 얼굴이 없으면 얼굴 지표는 비운다 (측정한 것만).
거울: 부스는 기본으로 컷을 좌우로 뒤집고 얼굴 박스도 같이 뒤집는다 (설정 mirror 기본 True). 이 도구도 시퀀스
meta.json 의 "mirror" (없으면 True) 를 따라 검출 · 고르기는 원본으로, 크롭 · 지표 · 합성은 뒤집은 컷으로 한다 —
좌우가 다른 프레임에서 부스와 같은 크롭이 나오게.
  face_cut_max / face_cut_mean  얼굴 박스 넓이 중 크롭 밖으로 나간 비율의 최댓값 · 평균
  all_in       모든 얼굴이 크롭 안에 온전히 들어왔으면 1, 아니면 0
  occluded     프레임 장식(occlusion_grid)이 슬롯 안 얼굴 자리를 가린 비율의 최댓값 (framing 의 비용과 같은 식)
  face_fill    얼굴 전체 합집합 박스(크롭으로 자르지 않은 것)의 가로/크롭 가로 · 세로/크롭 세로 중 큰 쪽 — 넓이 비율이 아니다.
               B · AB 는 기본 구도가 1.3배 확대라 설계상 face_fill 이 약 1.3배 크게 나온다 (효과가 아니라 정의에서 오는 차이).
  all_in_all / face_cut_max_all  위와 같지만 검출한 얼굴 전부(뒤쪽 작은 얼굴 포함) 기준
  eye_min      그 프레임 얼굴들의 눈 뜸 최솟값 (슬롯과 무관)
  ms           계산 비용만 = 분석(baseline 0 · B 셔터 프레임 검출 · A/AB 모든 프레임 검출 + 고르기)
               + 크롭 계산(슬롯 전부). 셔터 뒤 프레임 수집(약 0.3초) · 장식 격자 만들기 · 모델 불러오기는 빠진다.
               평가 PC 기준이고, 손님이 기다리는 전체 지연이 아니다.

자기 채점 주의 (보고서에 적을 것): all_in · face_cut · occluded 는 검출기 박스 기준이다. B · AB 는 바로 그 박스로
크롭을 고르고 occluded 는 그 비용 항목 그대로라, B · AB 에게는 자기 채점이다 (좋게 나오는 것이 당연한 쪽).
검출기가 놓친 얼굴은 어느 조건에서도 보이지 않고, *_all 이 아닌 열은 usable_faces 로 뒤쪽 작은 얼굴을 뺀다.
독립 확인은 가린 비교 시트로 받은 사람 평가('잘림' · '구도선호')다.

출력 (<out>, 기본 eval_data/_eval — git 에 올라가지 않는 곳):
  results.csv   시퀀스 × 조건 × 슬롯 한 줄씩 (UTF-8 BOM, 엑셀용)
  summary.csv   조건별 평균 · 실패 수 (+ labels.csv 가 있으면 사람 평가 평균). 슬롯끼리는 같은 컷이라 거의 같은 값이므로
                시퀀스마다 슬롯 평균을 먼저 내고 시퀀스끼리 평균한다 — 표본 수 n = 성공한 시퀀스 수.
  blind/<시퀀스>.jpg   네 조건의 합성 결과를 무작위 순서로 1~4 번호만 붙여 이어 붙인 가린 비교 시트
  blind_key.csv 답안 (시퀀스, 번호 → 조건). 이미 있으면 같은 시퀀스의 번호는 그대로 둔다 (사람 평가가 어긋나지 않게).
                새로 섞으려면 --reshuffle.
  debug/        --debug 일 때만: 조건 B · AB 의 프레임 위에 얼굴 박스 · 기본 구도(점선) · 결과 크롭(실선)

<root>/labels.csv (열: 시퀀스,번호,눈감음,흐림,잘림,구도선호 — 값은 0/1 또는 1~5, 빈칸 허용)가 있으면
답안으로 번호를 조건으로 바꿔 summary.csv 에 조건별 평균으로 합친다.
blind/ · debug/ 는 원본 얼굴 사진이 담긴다 — 확인 뒤 지우고, 저장소에 넣거나 밖으로 보내지 않는다.
이 도구는 로컬 파일만 읽고 아무것도 업로드하지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from tools.eval_sheets import (CONDITIONS, LABEL_COLS, _composite, blind_order, blind_sheet,  # noqa: E402
                               draw_debug, read_key, read_labels, write_key)
from tools.record_burst import EVAL_ROOT, load_sequence  # noqa: E402
from walnut import default_bundle  # noqa: E402
from walnut.analysis import DETECT_MODE, BurstAnalyzer, _mirror_box, framing_faces, stable_faces  # noqa: E402
from walnut.compose import cover_crop  # noqa: E402
from walnut.framing import _occlude, compute_crop, occlusion_grid, usable_faces  # noqa: E402
from walnut.quality import Candidate, FaceObs, select_best, sharpness  # noqa: E402

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "face_landmarker.task"
DEFAULT_OUT = EVAL_ROOT / "_eval"
EVAL_DETECT_MODE = "full+halves"
_SPEC = {"baseline": (False, False), "A": (True, False), "B": (False, True), "AB": (True, True)}  # (버스트, 구도 보정)
CENTER = "center"   # 가운데 크롭 조건의 reason
METRICS = ("face_cut_max", "face_cut_mean", "all_in", "occluded", "face_fill")
ALL_METRICS = ("all_in_all", "face_cut_max_all")   # 뒤쪽 작은 얼굴까지 검출한 얼굴 전부 기준
RESULT_HEADER = ["시퀀스", "조건", "슬롯", "프레임", "reason", "zoom", "크롭 x", "크롭 y", "크롭 w", "크롭 h",
                 "얼굴 수", "구도 얼굴 수", "걸러진 얼굴", "얼굴 빌림", *METRICS, *ALL_METRICS, "eye_min", "거울", "ms", "실패", "오류"]
SUMMARY_HEADER = ["조건", "표본 수(시퀀스)", "얼굴 있는 표본 수", "실패 수",
                  "face_cut_max 평균", "face_cut_mean 평균", "all_in 비율", "occluded 평균", "face_fill 평균",
                  "all_in_all 비율", "face_cut_max_all 평균",
                  "eye_min 평균", "ms 평균", "ms 최대", "사람 평가 수", *(f"{c} 평균" for c in LABEL_COLS)]
CAVEAT = ("주의: all_in · face_cut · occluded 는 검출기 박스 기준이라 B · AB 에게는 자기 채점이다 "
          "(같은 박스로 크롭을 고른다). 검출이 놓친 얼굴은 어느 조건에도 안 보이고, *_all 이 아닌 열은 뒤쪽 작은 얼굴을 뺀다. "
          "독립 확인은 사람 평가(잘림 · 구도선호).")


@dataclass
class SlotResult:
    slot: str
    crop: tuple[int, int, int, int]
    reason: str
    zoom: float
    metrics: dict


@dataclass
class Result:
    condition: str
    frame_index: int                     # 실패해 정하지 못했으면 -1
    slots: list[SlotResult] = field(default_factory=list)
    eye_min: float | None = None
    mirror: bool = False
    ms: float = 0.0
    failed: bool = False
    error: str = ""
    faces: list = field(default_factory=list, repr=False)   # 그 프레임에서 검출한 얼굴 전부 (거르기 전 — 채점 기준)
    unstable_faces: int = 0              # 버스트 조건: 꾸준히 잡히지 않아 뺀 얼굴 수 (부스 cut 줄과 같다)
    faces_from: int | None = None        # 버스트 조건: 구도용 얼굴을 빌려 온 프레임 번호
    person_heads: int = 0                # 구도 보정 조건: 사람 찾기로 크롭용 얼굴에 더한 추정 머리 수 (부스 cut 줄과 같다)
    rgb: np.ndarray | None = field(default=None, repr=False)


# ---- 지표 ----

def _clip01(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def slot_metrics(crop, pw: int, ph: int, faces, grid) -> dict:
    """크롭 하나의 얼굴 지표. faces 는 구도에 쓰는 얼굴 (여백 없는 박스). 얼굴이 없으면 모두 None.

    grid 가 None 이면 occluded 는 재지 않는다 (None).
    """
    empty = {k: None for k in METRICS}
    cx, cy, cw, ch = crop
    cuts, boxes = [], []
    for f in faces:
        x0, y0 = _clip01(f.box[0]) * pw, _clip01(f.box[1]) * ph
        x1, y1 = _clip01(f.box[2]) * pw, _clip01(f.box[3]) * ph
        area = (x1 - x0) * (y1 - y0)
        if area <= 0:
            continue
        inside = (max(0.0, min(x1, cx + cw) - max(x0, cx)) * max(0.0, min(y1, cy + ch) - max(y0, cy)))
        cuts.append(max(0.0, 1.0 - inside / area))
        boxes.append((x0, y0, x1, y1))
    if not cuts:
        return empty
    ux0, uy0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    ux1, uy1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    return {
        "face_cut_max": max(cuts),
        "face_cut_mean": sum(cuts) / len(cuts),
        "all_in": 1 if max(cuts) <= 1e-9 else 0,
        "occluded": None if grid is None else float(_occlude(crop, pw, ph, faces, grid)),
        "face_fill": max((ux1 - ux0) / cw, (uy1 - uy0) / ch),
    }


def _eye_min(faces) -> float | None:
    eyes = [f.eye_open for f in faces if f.eye_open is not None]
    return min(eyes) if eyes else None


def _frame_sharpness(rgb: np.ndarray, faces) -> float:
    """BurstAnalyzer._observe 와 같은 식: 얼굴 영역 선명도의 최솟값, 얼굴이 없으면 프레임 전체."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    sharps = [sharpness(gray, f.box) for f in faces]
    return min(sharps) if sharps else sharpness(gray)


# ---- 네 조건 ----

def _unpack(sequence):
    """(frames, shutter_t, meta). meta 가 없으면 빈 dict."""
    if isinstance(sequence, (str, Path)):
        sequence = load_sequence(Path(sequence))
    meta = sequence[2] if len(sequence) > 2 and isinstance(sequence[2], dict) else {}
    return list(sequence[0]), float(sequence[1]), meta


def _mirrored_faces(faces) -> list:
    """BurstAnalyzer._analyze 와 같다: 박스만 좌우로 뒤집고 눈 뜸 · 방향은 그대로."""
    return [FaceObs(_mirror_box(f.box), f.eye_open, f.frontality) for f in faces]


PERSON_TIMEOUT = 10.0   # 사람 찾기 한 장 기다리는 한도 (초). 처음 한 번은 모델 불러오기가 들어 있어 부스 ANALYZE_TIMEOUT 보다 넉넉히
log = logging.getLogger(__name__)


def _person_heads(analyzer, rgb: np.ndarray, faces) -> tuple[list, float]:
    """부스(BurstAnalyzer._analyze)와 같은 사람 찾기 → (추정 머리, ms). 기능이 없거나 실패하면 ([], 0)."""
    fn = getattr(analyzer, "person_heads_for", None)
    if fn is None:
        return [], 0.0
    try:
        heads, ms = fn(rgb, list(faces)).result(PERSON_TIMEOUT)
    except Exception as exc:
        log.warning("사람 찾기에 실패해 얼굴만으로 크롭합니다: %s", exc or type(exc).__name__)
        return [], 0.0
    return list(heads), float(ms or 0.0)


def run_conditions(sequence, frame_png: Image.Image, slots: list[dict], analyzer,
                   grids: list | None = None, mirror: bool | None = None) -> dict[str, Result]:
    """같은 시퀀스를 네 조건으로. sequence 는 (frames, shutter_t[, meta]) 또는 시퀀스 폴더.

    analyzer 는 detect_frames(frames, mode) -> Future[[(얼굴 목록, ms)]] 를 가진 것 (BurstAnalyzer).
    grids 는 슬롯 순서의 장식 격자 (없으면 여기서 만든다). 조건 하나의 예외는 그 조건의 실패로 남기고 계속한다.
    mirror 가 None 이면 meta 의 "mirror" (없으면 부스 기본값 True). 켜져 있으면 부스처럼 검출 · 고르기는 원본으로 하고,
    컷 이미지는 좌우로 뒤집고 얼굴 박스도 같이 뒤집은 뒤 크롭 · 지표 · 합성을 한다.
    """
    frames, shutter_t, meta = _unpack(sequence)
    if mirror is None:
        mirror = bool(meta.get("mirror", True))
    if grids is None:
        grids = [occlusion_grid(frame_png, s) for s in slots]
    nearest = min(range(len(frames)), key=lambda i: (abs(frames[i].t - shutter_t), i)) if frames else 0
    try:
        # 부스와 같이 사람별 얼굴 다시 찾기까지 (BurstAnalyzer.detect_burst). 없는 분석기(시험용 가짜)는 검출만
        burst_fn = getattr(analyzer, "detect_burst", None)
        det = (burst_fn([f.rgb for f in frames], nearest, EVAL_DETECT_MODE) if burst_fn and frames
               else analyzer.detect_frames([f.rgb for f in frames], EVAL_DETECT_MODE)).result()
        if len(det) != len(frames):
            raise ValueError(f"검출 결과 수({len(det)})가 프레임 수({len(frames)})와 다르다")
        faces = [list(fs) for fs, _ in det]
        det_ms = [float(ms) for _, ms in det]
    except Exception as exc:
        return {c: Result(c, -1, failed=True, error=f"분석 실패: {exc}") for c in CONDITIONS}

    sel_index, sel_ms, sel_err = None, 0.0, None
    crop_faces, faces_from, unstable = [], None, 0
    try:
        cands = [Candidate(f.t, _frame_sharpness(f.rgb, faces[i]), faces[i]) for i, f in enumerate(frames)]
        t0 = time.perf_counter()
        # 부스(BurstAnalyzer._analyze)와 같은 순서: 꾸준한 얼굴로 고르기 → 고른 프레임 얼굴 전부(없으면 빌리기)로 구도
        kept, unstable = stable_faces(cands, lambda i, fs: _frame_sharpness(frames[i].rgb, fs))
        sel_index = select_best(kept, shutter_t).index
        crop_faces, faces_from, _, _ = framing_faces(cands, kept, sel_index)
        sel_ms = (time.perf_counter() - t0) * 1000.0
    except Exception as exc:
        sel_err = exc
    # 구도 보정 조건이 크롭에 쓰는 얼굴 + 사람 찾기 머리 (원본 좌표, 거울은 아래에서). 사람 찾기는 부스처럼 둘 다 셔터 프레임에서
    ab_heads, ab_ms = ([], 0.0) if sel_err is not None else _person_heads(analyzer, frames[nearest].rgb, crop_faces)
    b_heads, b_ms = _person_heads(analyzer, frames[nearest].rgb, faces[nearest])

    out = {}
    for cond in CONDITIONS:
        burst, smart = _SPEC[cond]
        try:
            if burst and sel_err is not None:
                raise RuntimeError(f"베스트 컷 고르기 실패: {sel_err}")
            idx = sel_index if burst else nearest
            analysis_ms = (sum(det_ms) + sel_ms) if burst else (det_ms[nearest] if smart else 0.0)
            heads, heads_ms = ((ab_heads, ab_ms) if burst else (b_heads, b_ms)) if smart else ([], 0.0)
            analysis_ms += heads_ms
            rgb = frames[idx].rgb[:, ::-1] if mirror else frames[idx].rgb   # capture.mirrored 와 같다
            ph, pw = rgb.shape[:2]
            # 채점은 네 조건 모두 그 프레임에서 검출한 얼굴 그대로 (거르기 전) — 같은 얼굴로 비교한다.
            # 거른 · 빌린 얼굴은 부스가 실제로 쓰는 곳(버스트 조건의 고르기 · 크롭)에만 쓴다.
            for_crop = (crop_faces if burst else faces[idx]) + heads
            fs = _mirrored_faces(faces[idx]) if mirror else faces[idx]
            cfs = _mirrored_faces(for_crop) if mirror else for_crop
            t0 = time.perf_counter()
            crops = []
            for slot, grid in zip(slots, grids):
                if smart:
                    c = compute_crop(pw, ph, slot["w"], slot["h"], cfs, grid)
                    crops.append(((c.x, c.y, c.w, c.h), c.reason))
                else:
                    crops.append((cover_crop(pw, ph, slot["w"], slot["h"]), CENTER))
            crop_ms = (time.perf_counter() - t0) * 1000.0
            used = usable_faces(fs)
            slot_results = []
            for slot, grid, (crop, reason) in zip(slots, grids, crops):
                base_w = cover_crop(pw, ph, slot["w"], slot["h"])[2]
                m = slot_metrics(crop, pw, ph, used, grid)
                every = slot_metrics(crop, pw, ph, fs, None)   # 검출한 얼굴 전부
                m["all_in_all"], m["face_cut_max_all"] = every["all_in"], every["face_cut_max"]
                slot_results.append(SlotResult(slot["id"], tuple(int(v) for v in crop), reason,
                                               base_w / crop[2], m))
            out[cond] = Result(cond, idx, slot_results, _eye_min(used), bool(mirror), analysis_ms + crop_ms,
                               faces=fs, unstable_faces=unstable if burst else 0,
                               faces_from=faces_from if burst else None, person_heads=len(heads), rgb=np.ascontiguousarray(rgb))
        except Exception as exc:
            out[cond] = Result(cond, -1, failed=True, error=str(exc) or type(exc).__name__)
    return out


# ---- 시퀀스 찾기 ----

def find_sequences(root: Path) -> list[tuple[str, Path]]:
    """[(시퀀스 id, 폴더)]. eval_data/* 와 eval_data/field_*/* 중 meta.json 이 있는 것, id 순."""
    root = Path(root)
    if not root.is_dir():
        return []
    found = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        if (d / "meta.json").is_file():
            found.append((d.name, d))
        elif d.name.startswith("field_"):
            found.extend((f"{d.name}/{s.name}", s) for s in d.iterdir()
                         if s.is_dir() and (s / "meta.json").is_file())
    return sorted(found)


# ---- CSV ----

def _f(v, digits: int = 4) -> str:
    return "" if v is None else f"{v:.{digits}f}"


def _mean(vals: list) -> float | None:
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


def result_rows(seq_id: str, slots: list[dict], results: dict[str, Result]) -> list[list]:
    rows = []
    for cond in CONDITIONS:
        r = results[cond]
        if r.failed:
            rows.extend([seq_id, cond, s["id"], *[""] * (len(RESULT_HEADER) - 5), 1, r.error] for s in slots)
            continue
        for sr in r.slots:
            m = sr.metrics
            rows.append([seq_id, cond, sr.slot, r.frame_index, sr.reason, f"{sr.zoom:.3f}", *sr.crop,
                         len(r.faces), len(usable_faces(r.faces)), r.unstable_faces,
                         "" if r.faces_from is None else r.faces_from,
                         _f(m["face_cut_max"]), _f(m["face_cut_mean"]),
                         "" if m["all_in"] is None else m["all_in"], _f(m["occluded"]), _f(m["face_fill"]),
                         "" if m["all_in_all"] is None else m["all_in_all"], _f(m["face_cut_max_all"]),
                         _f(r.eye_min), int(r.mirror), f"{r.ms:.2f}", 0, ""])
    return rows


def _seq_mean(r: Result, k: str) -> float | None:
    """한 시퀀스(컷)의 지표: 값이 있는 슬롯들의 평균. 슬롯끼리는 같은 컷이라 거의 같은 값이므로 표본으로 세지 않는다."""
    return _mean([sr.metrics[k] for sr in r.slots])


def summarize(all_results: list[tuple[str, dict[str, Result]]], labels: dict[str, dict]) -> list[dict]:
    """조건별 요약. 시퀀스마다 슬롯 평균을 먼저 낸 뒤 시퀀스끼리 평균한다 — 표본 수 n = 성공한 시퀀스 수.

    평균은 값이 있는 시퀀스(얼굴이 있는 표본)만으로 낸다. 슬롯별 값은 results.csv 에 있다.
    """
    out = []
    for cond in CONDITIONS:
        ok = [res[cond] for _, res in all_results if not res[cond].failed]
        col = lambda k: [_seq_mean(r, k) for r in ok]  # noqa: E731
        ms = [r.ms for r in ok]
        lab = labels.get(cond)
        s = {
            "조건": cond, "표본 수(시퀀스)": len(ok),
            "얼굴 있는 표본 수": sum(1 for v in col("all_in") if v is not None),
            "실패 수": sum(1 for _, res in all_results if res[cond].failed),
            "face_cut_max 평균": _f(_mean(col("face_cut_max"))),
            "face_cut_mean 평균": _f(_mean(col("face_cut_mean"))),
            "all_in 비율": _f(_mean(col("all_in"))),
            "occluded 평균": _f(_mean(col("occluded"))),
            "face_fill 평균": _f(_mean(col("face_fill"))),
            "all_in_all 비율": _f(_mean(col("all_in_all"))),
            "face_cut_max_all 평균": _f(_mean(col("face_cut_max_all"))),
            "eye_min 평균": _f(_mean([r.eye_min for r in ok])),
            "ms 평균": _f(_mean(ms), 2), "ms 최대": _f(max(ms) if ms else None, 2),
            "사람 평가 수": lab["n"] if lab else "",
        }
        for c in LABEL_COLS:
            s[f"{c} 평균"] = _f(_mean(lab[c])) if lab else ""
        out.append(s)
    return out


def _write_csv(path: Path, header: list[str], rows: list) -> None:
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for row in rows:
            w.writerow([row[h] for h in header] if isinstance(row, dict) else row)


def format_summary(s: dict) -> str:
    def p(k):
        return s[k] or "-"
    line = (f"{s['조건']:<8}  n {s['표본 수(시퀀스)']}  실패 {s['실패 수']}  "
            f"all_in {p('all_in 비율')} (전부 {p('all_in_all 비율')})  잘림 최대 {p('face_cut_max 평균')}  "
            f"가림 {p('occluded 평균')}  "
            f"채움 {p('face_fill 평균')}  눈 뜸 {p('eye_min 평균')}  {p('ms 평균')}ms")
    if s["사람 평가 수"] not in ("", 0):
        line += "  사람 " + "  ".join(f"{c} {p(c + ' 평균')}" for c in LABEL_COLS)
    return line


# ---- 실행 ----

def run(root: Path, frame_png: Image.Image, slots: list[dict], analyzer, out: Path, seed=None,
        debug: bool = False, reshuffle: bool = False, log=print) -> list[tuple[str, dict[str, Result]]]:
    root, out = Path(root), Path(out)
    grids = [occlusion_grid(frame_png, s) for s in slots]
    old_key = read_key(out / "blind_key.csv")
    all_results, rows, key = [], [], {}
    for seq_id, d in find_sequences(root):
        try:
            sequence = load_sequence(d)
        except Exception as exc:  # 시퀀스 하나가 깨져도 나머지는 계속한다
            log(f"{seq_id}  읽지 못해 건너뜀: {exc}")
            continue
        results = run_conditions(sequence, frame_png, slots, analyzer, grids)
        all_results.append((seq_id, results))
        rows.extend(result_rows(seq_id, slots, results))
        brief = "  ".join(f"{c}={'실패' if r.failed else ','.join(sorted({s.reason for s in r.slots}))}"
                          for c, r in results.items())
        log(f"{seq_id}  {brief}")

        shown = [c for c in CONDITIONS if not results[c].failed]
        if shown:
            old = old_key.get(seq_id)
            order = blind_order(seq_id, shown, old, seed, reshuffle)
            if old and order != [old[k] for k in sorted(old)]:
                log(f"{seq_id}  답안 번호를 새로 정했습니다 — 이 시퀀스의 예전 사람 평가는 다시 해야 합니다")
            key[seq_id] = order
            sheet = blind_sheet([_composite(frame_png, slots, results[c]) for c in order])
            path = out / "blind" / f"{seq_id}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            sheet.save(path, "JPEG", quality=90)
        if debug:
            for cond in ("B", "AB"):
                r = results[cond]
                if r.failed:
                    continue
                for slot, sr in zip(slots, r.slots):
                    draw_debug(r, slot, sr, out / "debug" / f"{seq_id}_{cond}_{sr.slot}.jpg")

    if not all_results:
        log(f"평가할 시퀀스가 없습니다: {root}")
        return all_results
    for seq_id, order in old_key.items():  # 이번에 없던 시퀀스의 답안은 지우지 않는다
        if seq_id not in key:
            key[seq_id] = [order[k] for k in sorted(order)]
    out.mkdir(parents=True, exist_ok=True)
    write_key(out / "blind_key.csv", key)
    _write_csv(out / "results.csv", RESULT_HEADER, rows)
    summary = summarize(all_results, read_labels(root, key, log))
    _write_csv(out / "summary.csv", SUMMARY_HEADER, summary)
    log("조건별 요약 (시퀀스마다 슬롯 평균 → 시퀀스 평균, n = 시퀀스 수, 얼굴 있는 표본만):")
    for s in summary:
        log(format_summary(s))
    log(CAVEAT)
    log(f"결과를 썼습니다: {out / 'results.csv'} · {out / 'summary.csv'} · 답안 {out / 'blind_key.csv'}")
    log(f"가린 비교 시트: {out / 'blind'} (원본 얼굴 사진이 담깁니다 — 평가 뒤 지우세요)")
    log("평가자에게는 blind 폴더만 주고 blind_key.csv(답안)는 주지 마세요.")
    if debug:
        log(f"디버그 그림을 썼습니다 — 원본 얼굴 사진이니 확인 뒤 바로 지우세요: {out / 'debug'}")
    return all_results


def frame_slots(path: Path) -> tuple[Image.Image, list[dict]]:
    """프레임 PNG 와 슬롯. 같은 이름의 .json 에 slots 가 있으면 그것을, 없으면 투명 구멍을 찾는다 (부스와 같다)."""
    path = Path(path)
    img = Image.open(path)
    img.load()
    side = path.with_suffix(".json")
    if side.is_file():
        slots = json.loads(side.read_text(encoding="utf-8"))["slots"]
    else:
        slots = default_bundle.detect_slots(img)
    return img, slots


def default_frame() -> Path:
    """시험용 프레임 폴더(assets/frame)에서 슬롯이 있는 첫 PNG, 없으면 기본 프레임."""
    for p in sorted(Path(default_bundle.FRAME_DIR).glob("*.png")):
        try:
            if frame_slots(p)[1]:
                return p
        except Exception:
            continue
    return Path(default_bundle.__file__).resolve().parent / "default_frame" / "frame.png"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="4조건 비교 평가 도구 (로컬 파일만 읽고 아무것도 업로드하지 않는다)")
    ap.add_argument("--root", type=Path, default=EVAL_ROOT, help="시퀀스 폴더들이 있는 곳 (기본 booth/eval_data)")
    ap.add_argument("--frame", type=Path, default=None, help="합성할 프레임 PNG (기본 assets/frame 첫 장 또는 기본 프레임)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="결과 폴더 (기본 booth/eval_data/_eval)")
    ap.add_argument("--seed", type=int, default=None, help="가린 비교 시트 순서의 난수 시드")
    ap.add_argument("--reshuffle", action="store_true", help="이미 있는 답안을 무시하고 순서를 새로 섞는다")
    ap.add_argument("--debug", action="store_true", help="얼굴 박스 · 크롭을 그린 그림을 쓴다 (원본 얼굴 사진, 기본 끔)")
    args = ap.parse_args(argv)

    frame_path = args.frame or default_frame()
    frame_png, slots = frame_slots(frame_path)
    if not slots:
        print(f"프레임에서 슬롯(투명 구멍)을 찾지 못했습니다: {frame_path}")
        return 1
    print(f"프레임 {frame_path.name} · 슬롯 {len(slots)}개 · 검출 {EVAL_DETECT_MODE}")
    if DETECT_MODE != EVAL_DETECT_MODE:
        print(f"주의: 부스 검출 전략({DETECT_MODE})이 평가 전략({EVAL_DETECT_MODE})과 다릅니다")
    if args.debug:
        print("주의: --debug 는 원본 얼굴 사진에 박스를 그려 저장합니다. 확인 뒤 지우고 밖으로 보내지 마세요.")
    analyzer = BurstAnalyzer(MODEL_PATH, detect_mode=EVAL_DETECT_MODE)
    if not analyzer.available:
        print(f"얼굴 모델이 없습니다: {MODEL_PATH} (tools/download_models.py)")
        return 1
    try:
        analyzer.warm()  # 모델 불러오기를 첫 시퀀스의 ms 에 넣지 않는다
        run(args.root, frame_png, slots, analyzer, args.out, seed=args.seed, debug=args.debug,
            reshuffle=args.reshuffle)
    finally:
        analyzer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
