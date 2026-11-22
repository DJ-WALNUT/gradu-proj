"""MediaPipe Face Landmarker 래퍼.

- mediapipe 는 첫 faces() 호출 때 불러온다. 스티커를 안 쓰는 행사는 아예 로드하지 않는다.
- 모델 파일이 없거나 불러오기에 실패하면 available=False — 스티커 단계는 건너뛴다.
- VIDEO 모드는 타임스탬프가 반드시 증가해야 한다.
- 추론은 INFER_WIDTH 로 줄인 사본에서 한다. 결과 좌표는 0~1 이라 원본에 그대로 쓴다.
mediapipe 는 0.10.21 로 고정한다 (requirements.txt).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

INFER_WIDTH = 640


class FaceDetector:
    def __init__(self, model_path: Path, max_faces: int = 4):
        self.model_path = Path(model_path)
        self.max_faces = max_faces
        self.available = self.model_path.is_file()
        if not self.available:
            log.warning("얼굴 모델이 없어 스티커를 건너뜁니다: %s (tools/download_models.py)", self.model_path)
        self._model = None
        self._mp = None
        self._last_ts = 0

    def _load(self) -> None:
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions, vision

            opts = vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=str(self.model_path)),
                running_mode=vision.RunningMode.VIDEO, num_faces=self.max_faces,
                min_face_detection_confidence=0.5, min_tracking_confidence=0.5)
            self._model = vision.FaceLandmarker.create_from_options(opts)
            self._mp = mp
        except Exception as exc:  # import 실패, 모델 손상 등
            log.error("얼굴 인식을 켤 수 없어 스티커를 건너뜁니다: %s", exc)
            self.available = False

    def faces(self, rgb: np.ndarray) -> list[list]:
        """얼굴마다 478개 정규화 랜드마크. 없거나 쓸 수 없으면 빈 목록."""
        if not self.available:
            return []
        if self._model is None:
            self._load()
            if self._model is None:
                return []
        h, w = rgb.shape[:2]
        if w > INFER_WIDTH:
            import cv2

            rgb = cv2.resize(rgb, (INFER_WIDTH, max(1, int(h * INFER_WIDTH / w))), interpolation=cv2.INTER_AREA)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        ts = max(self._last_ts + 1, int(time.monotonic() * 1000))
        self._last_ts = ts
        try:
            return list(self._model.detect_for_video(image, ts).face_landmarks or [])
        except Exception as exc:
            log.error("얼굴 인식 오류: %s", exc)
            return []

    def close(self) -> None:
        if self._model is not None:
            self._model.close()
            self._model = None
