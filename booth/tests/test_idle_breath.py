"""대기 화면 시작 버튼 숨쉬기 — 크기가 정수 계단이 아니라 연속으로 변한다."""

import math

import numpy as np
import pygame
import pytest

from walnut import ui
from walnut.booth_design import load as load_tokens
from walnut.scenes.idle import IdleScene
from tests.test_app import _save_device, paired_with_bundle  # noqa: F401
from tests.test_touch_scenes import app  # noqa: F401

BREATH = load_tokens()["motion"]["breath"]


def test_sprite_scale_changes_coverage_below_one_pixel():
    src = pygame.Surface((201, 101), pygame.SRCALPHA)
    src.fill((255, 255, 255, 255), pygame.Rect(10, 10, 181, 81))
    sprite = ui.ScaledSprite(src)
    sums = []
    for scale in (0.990, 0.991, 0.992, 0.993):  # 181px 의 0.1% — 한 픽셀에 한참 못 미친다
        dst = pygame.Surface((201, 101))
        sprite.blit(dst, (100, 50), scale)
        sums.append(int(pygame.surfarray.array3d(dst).sum()))
    assert sums == sorted(sums) and len(set(sums)) == 4


def test_sprite_scale_one_keeps_pixels_and_blends_over_background():
    src = pygame.Surface((40, 20), pygame.SRCALPHA)
    src.fill((200, 100, 50, 128), pygame.Rect(0, 0, 40, 20))
    dst = pygame.Surface((40, 20))
    dst.fill((0, 0, 100))
    ui.ScaledSprite(src).blit(dst, (20, 10), 1.0)
    r, g, b = dst.get_at((20, 10))[:3]
    assert abs(r - 100) <= 2 and abs(g - 50) <= 2 and abs(b - 75) <= 2


def _coverage(app, t: float, box: pygame.Rect) -> float:
    """버튼 자리에서 배경과 달라진 정도의 합 — 버튼이 커지면 커진다."""
    scene = app.scene
    scene.t = t
    surf = pygame.Surface(app.screen.get_size())
    surf.fill((0, 0, 0))
    scene.draw(surf)
    return float(pygame.surfarray.array3d(surf.subsurface(box)).astype(np.int64).sum())


def test_button_grows_every_frame_while_breathing_in(app):
    assert isinstance(app.scene, IdleScene)
    box = app.scene.start_rect().inflate(8, 8)
    speed = math.pi * 1000 / BREATH["half_ms"]
    t0 = -math.pi / 4 / speed  # 들숨 한가운데 앞쪽
    frames = [_coverage(app, t0 + i / 60, box) for i in range(12)]
    steps = np.diff(frames)
    assert (steps != 0).all(), f"멈춘 프레임이 있습니다: {steps}"


def test_tap_area_does_not_move_with_breath(app):
    scene = app.scene
    scene.t = 0.0
    a = scene.start_rect().copy()
    scene.t = 0.7
    assert scene.start_rect() == a


def test_focus_ring_is_not_clipped(app):
    """키 입력일 때 버튼 바깥 고리가 그려 둔 판 끝에서 잘리면 안 된다."""
    scene = app.scene
    app.input_kind = "key"
    rgba = scene._button_for(scene.start_rect())._rgba
    edge = np.concatenate((rgba[0, :, 3], rgba[-1, :, 3], rgba[:, 0, 3], rgba[:, -1, 3]))
    assert edge.max() == 0
    assert rgba[..., 3].max() == 255
