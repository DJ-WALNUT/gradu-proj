"""효과음 — 파일 없이 사인파로 만든다. 오디오 장치가 없으면 조용히 꺼진다."""

from __future__ import annotations

import logging

import numpy as np
import pygame

log = logging.getLogger(__name__)

_SOUNDS: dict[str, pygame.mixer.Sound] = {}
RATE = 44100


def _tone(freqs: list[tuple[float, float]], volume: float = 0.35) -> np.ndarray:
    parts = []
    for freq, dur in freqs:
        t = np.linspace(0, dur, int(RATE * dur), endpoint=False)
        wave = np.sin(2 * np.pi * freq * t) if freq > 0 else np.zeros_like(t)
        env = np.minimum(1, np.minimum(t / 0.01, (dur - t) / 0.04))  # 딸깍 소리 방지
        parts.append(wave * np.clip(env, 0, 1))
    mono = (np.concatenate(parts) * volume * 32767).astype(np.int16)
    return np.column_stack([mono, mono])


def init() -> None:
    _SOUNDS.clear()
    try:
        pygame.mixer.pre_init(RATE, -16, 2, 512)
        pygame.mixer.init()
    except pygame.error as exc:
        log.warning("[sfx] 오디오 장치를 열 수 없어 효과음을 끕니다: %s", exc)
        return
    recipes = {
        "tick": [(880, 0.08)],
        "go": [(660, 0.08), (990, 0.18)],
        "item": [(1320, 0.05), (1760, 0.08)],
        "bonus": [(988, 0.06), (1319, 0.06), (1760, 0.12)],
        "hit": [(220, 0.12), (150, 0.18)],
        "shutter": [(2000, 0.03), (0, 0.02), (1200, 0.05)],
        "clear": [(784, 0.1), (988, 0.1), (1175, 0.1), (1568, 0.25)],
        "stamp": [(330, 0.06), (660, 0.22)],
    }
    try:
        for name, rec in recipes.items():
            _SOUNDS[name] = pygame.sndarray.make_sound(_tone(rec))
    except pygame.error as exc:  # 장치가 모노 등 다른 형식으로 열린 경우
        log.warning("[sfx] 효과음을 만들 수 없어 끕니다: %s", exc)
        _SOUNDS.clear()


def play(name: str) -> None:
    snd = _SOUNDS.get(name)
    if snd is not None:
        snd.play()
