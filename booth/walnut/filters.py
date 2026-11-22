"""컷 필터: 채널별 256단계 LUT. 미리보기와 최종 컷이 같은 함수를 쓴다."""

from __future__ import annotations

import math

import numpy as np

FILTERS = ("original", "mono", "bright", "warm", "cool", "vintage")

# 이름 → 채널별 (기울기, 더하는 값). 결과는 floor(x + 0.5) 후 0~255 로 자른다.
_PARAMS = {
    "original": ((1.0, 0), (1.0, 0), (1.0, 0)),
    "bright": ((1.12, 12), (1.12, 12), (1.12, 12)),
    "warm": ((1.0, 18), (1.0, 4), (1.0, -14)),
    "cool": ((1.0, -14), (1.0, 2), (1.0, 18)),
    "vintage": ((0.85, 38), (0.85, 28), (0.80, 22)),
}


def _make_lut(gain: float, bias: float) -> np.ndarray:
    # float64 로 계산해야 155.5 같은 경계값이 정확히 올림된다.
    v = np.arange(256, dtype=np.float64)
    return np.clip(np.floor(gain * v + bias + 0.5), 0, 255).astype(np.uint8)


_LUTS = {name: [_make_lut(g, b) for g, b in ch] for name, ch in _PARAMS.items()}


def apply_filter(rgb: np.ndarray, name: str) -> np.ndarray:
    """uint8 HxWx3 → 새 uint8 HxWx3. 모르는 이름은 original."""
    if name == "mono":
        f = rgb.astype(np.float64)
        y = np.floor(0.299 * f[..., 0] + 0.587 * f[..., 1] + 0.114 * f[..., 2] + 0.5)
        y = np.clip(y, 0, 255).astype(np.uint8)
        return np.repeat(y[..., None], 3, axis=2)
    luts = _LUTS.get(name, _LUTS["original"])
    out = np.empty(rgb.shape, np.uint8)
    for c in range(3):
        out[..., c] = luts[c][rgb[..., c]]
    return out
