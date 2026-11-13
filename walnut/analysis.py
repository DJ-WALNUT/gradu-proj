"""버스트 분석기 — 별도 스레드에서 얼굴 모델로 프레임을 평가하고 베스트 한 장을 고른다.

- 촬영 장면이 쓰는 FaceDetector(app.detector)와 공유하지 않는 별도 FaceLandmarker 를 쓴다
  (IMAGE 모드, 블렌드셰이프 · 변환 행렬 출력).
- 작업 스레드는 하나다. 모델 불러오기 · 추론 · 닫기가 모두 그 스레드에서 일어난다.
- 분석 실패가 촬영을 멈추면 안 된다. 프레임 하나의 오류는 '얼굴 없음' 후보로 바꾸고,
  그 밖의 예외는 Future 에 실려 호출한 쪽이 처리한다.
- 입력 프레임은 읽기만 한다 (쓰지 않는다).
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .burst import TimedFrame
from .quality import (Candidate, FaceObs, _min_metric, eye_open_from, frontality_from,
                      select_best, sharpness)

log = logging.getLogger(__name__)

INFER_LONG_SIDE = 640  # 추론용 사본의 긴 변


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


def _mirror_box(box: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    return (1.0 - box[2], box[1], 1.0 - box[0], box[3])


class BurstAnalyzer:
    def __init__(self, model_path: Path, max_faces: int = 4, landmarker=None):
        self.model_path = Path(model_path)
        self.max_faces = max_faces
        self._landmarker = landmarker
        self._owns_landmarker = landmarker is None
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

    def _close_landmarker(self) -> None:
        lm, self._landmarker = self._landmarker, None
        if lm is not None and self._owns_landmarker:
            try:
                lm.close()
            except Exception as exc:
                log.warning("얼굴 모델을 닫는 중 오류: %s", exc)

    def _detect(self, rgb: np.ndarray):
        import mediapipe as mp

        h, w = rgb.shape[:2]
        long_side = max(h, w)
        if long_side > INFER_LONG_SIDE:
            s = INFER_LONG_SIDE / long_side
            rgb = cv2.resize(rgb, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        return self._landmarker.detect(image)

    def _observe(self, rgb: np.ndarray, gray: np.ndarray) -> tuple[float, list[FaceObs]]:
        """프레임 하나의 (선명도, 얼굴 목록). 오류는 호출한 쪽이 처리한다."""
        h, w = rgb.shape[:2]
        aspect = w / h
        res = self._detect(rgb)
        lms = list(res.face_landmarks or [])
        blends = list(getattr(res, "face_blendshapes", None) or [])
        mats = list(getattr(res, "facial_transformation_matrixes", None) or [])
        faces, sharps = [], []
        for i, lm in enumerate(lms):
            box = _face_box(lm)
            eye = eye_open_from(blends[i] if i < len(blends) else None, lm, aspect)
            pose = frontality_from(mats[i] if i < len(mats) else None)
            faces.append(FaceObs(box, eye, pose))
            sharps.append(sharpness(gray, box))
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
        self._ensure_loaded()
        t_loaded = time.perf_counter()  # 처음 한 번의 모델 불러오기는 detect 에 넣지 않는다
        if not self.available:
            raise RuntimeError("얼굴 모델을 쓸 수 없어 분석하지 못했습니다")
        cands = [self._evaluate(f) for f in frames]
        t_detect = time.perf_counter()
        sel = select_best(cands, shutter_t)
        t_select = time.perf_counter()

        faces = cands[sel.index].faces
        if mirror:
            faces = [FaceObs(_mirror_box(f.box), f.eye_open, f.frontality) for f in faces]
        info = {
            "reason": sel.reason,
            "fallback_used": bool(sel.fallback_used),
            "scores": [None if s is None else float(s) for s in sel.scores],
            "rejects": list(sel.rejects),
            "index": int(sel.index),
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
                "total": (time.perf_counter() - t_start) * 1000.0,
            },
        }
        return BurstResult(frames[sel.index].rgb, faces, info)

    # ---- 호출하는 쪽 API ----
    def warm(self) -> None:
        """모델을 작업 스레드에서 미리 불러오도록 예약한다. 기다리지 않고, 실패해도 예외를 던지지 않는다."""
        with self._lock:
            if self._closed:
                return
            self._executor.submit(self._ensure_loaded)

    def submit(self, frames: list[TimedFrame], shutter_t: float, mirror: bool) -> Future:
        with self._lock:
            if self._closed:
                raise RuntimeError("분석기가 이미 닫혀 있어 새 분석을 맡길 수 없습니다")
            return self._executor.submit(self._analyze, list(frames), shutter_t, mirror)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._executor.submit(self._close_landmarker)
            self._executor.shutdown(wait=False)


def _opt(v: float | None) -> float | None:
    return None if v is None else float(v)
