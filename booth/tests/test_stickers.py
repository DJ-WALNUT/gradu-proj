from __future__ import annotations

import math

import numpy as np
from PIL import Image

from tests.facekit import fake_face
from walnut.ar import geometry
from walnut.stickers import Sticker, draw_stickers, load_stickers, place


def sticker(anchor="forehead", scale=1.0, offset=(0.0, 0.0), size=(40, 20), color=(255, 0, 0, 255)):
    return Sticker("s", "스티커", Image.new("RGBA", size, color), anchor, scale, offset)


def test_place_upright_face():
    g = geometry(fake_face(cx=0.5, cy=0.5, w=0.2, h=0.3, roll=0), 1000, 1000)
    (x, y), w, roll = place(g, sticker("forehead", 1.5, (0.0, -0.4)))
    assert abs(w - 1.5 * g.width) < 1e-6 and abs(roll) < 1e-6
    assert abs(x - g.forehead[0]) < 1e-6 and abs(y - (g.forehead[1] - 0.4 * g.height)) < 1e-6


def test_place_follows_roll():
    g = geometry(fake_face(w=0.2, h=0.3, roll=30), 1000, 1000)
    (x, y), w, roll = place(g, sticker("eyes", 1.0, (0.5, 0.25)))
    assert abs(roll - 30) < 1e-3
    right = np.array([math.cos(math.radians(30)), -math.sin(math.radians(30))])  # 화면에서 반시계 30° 기울어진 눈 벡터
    down = np.array([math.sin(math.radians(30)), math.cos(math.radians(30))])
    eyes = (np.array([fake_face(w=0.2, h=0.3, roll=30)[i].x for i in (33, 263)]).mean() * 1000,
            np.array([fake_face(w=0.2, h=0.3, roll=30)[i].y for i in (33, 263)]).mean() * 1000)
    want = np.array(eyes) + 0.5 * g.width * right + 0.25 * g.height * down
    assert abs(x - want[0]) < 1e-3 and abs(y - want[1]) < 1e-3


def test_each_anchor_point():
    f = fake_face(cx=0.4, cy=0.6)
    g = geometry(f, 1000, 1000)

    def px(*idx):
        return (sum(f[i].x for i in idx) / len(idx) * 1000, sum(f[i].y for i in idx) / len(idx) * 1000)

    for anchor, idx in {"forehead": (10,), "eyes": (33, 263), "nose": (1,), "cheeks": (50, 280), "chin": (152,)}.items():
        (x, y), _, _ = place(g, sticker(anchor))
        assert abs(x - px(*idx)[0]) < 1e-3 and abs(y - px(*idx)[1]) < 1e-3, anchor


def test_draw_stickers_paints_only_near_face():
    rgb = np.zeros((400, 400, 3), np.uint8)
    out = draw_stickers(rgb, [fake_face(0.5, 0.5, 0.2, 0.3)], sticker("nose", 0.5, size=(10, 10)))
    assert out is not rgb and rgb.sum() == 0
    ys, xs = np.nonzero(out[..., 0])
    assert len(xs) > 0 and abs(xs.mean() - 200) < 20 and abs(ys.mean() - 200) < 40
    assert out[0, 0].sum() == 0 and out[399, 399].sum() == 0


def test_draw_stickers_clips_at_edges():
    rgb = np.zeros((200, 200, 3), np.uint8)
    out = draw_stickers(rgb, [fake_face(0.02, 0.02, 0.3, 0.4)], sticker("eyes", 3.0))  # 프레임 밖으로 나가도 예외 없음
    assert out.shape == rgb.shape and out.sum() > 0


def test_draw_stickers_limits_to_four_largest():
    rgb = np.zeros((1000, 1000, 3), np.uint8)  # 얼굴 폭 50~90px: 전부 크기 문턱을 넘는다
    faces = [fake_face(0.1 + 0.2 * i, 0.5, 0.05 + 0.01 * i, 0.06) for i in range(5)]
    out = draw_stickers(rgb, faces, sticker("nose", 1.0, size=(8, 8)))
    red = out[..., 0] > 0
    assert not red[:, :160].any()  # 가장 작은 얼굴(x=0.1) 은 건너뛴다
    for i in range(1, 5):
        cx = int((0.1 + 0.2 * i) * 1000)
        assert red[:, cx - 40:cx + 40].any(), i


def test_draw_stickers_skips_tiny_face():
    rgb = np.zeros((100, 100, 3), np.uint8)
    assert draw_stickers(rgb, [fake_face(0.5, 0.5, 0.15, 0.2)], sticker("nose")).sum() == 0  # 15px
    assert draw_stickers(rgb, [fake_face(0.5, 0.5, 0.25, 0.3)], sticker("nose")).sum() > 0  # 25px


def test_draw_stickers_no_faces_returns_copy():
    rgb = np.ones((10, 10, 3), np.uint8)
    out = draw_stickers(rgb, [], sticker())
    assert out is not rgb and (out == rgb).all()


def _settings(items, enabled=True):
    return {"stickers": {"enabled": enabled, "items": items}}


def _item(sid, asset):
    return {"id": sid, "name": sid, "asset": asset, "anchor": "eyes", "scale": 1.2, "offset": [0.1, -0.2]}


def test_load_stickers_skips_broken_asset(tmp_path):
    Image.new("RGBA", (8, 4), (1, 2, 3, 255)).save(tmp_path / "good", "PNG")
    (tmp_path / "bad").write_bytes(b"not an image")
    items = [_item("a", "good"), _item("b", "bad"), _item("c", "missing")]
    out = load_stickers(_settings(items), lambda sha: tmp_path / sha)
    assert [s.id for s in out] == ["a"]
    s = out[0]
    assert s.image.mode == "RGBA" and s.anchor == "eyes" and s.scale == 1.2 and s.offset == (0.1, -0.2)


def test_load_stickers_disabled(tmp_path):
    Image.new("RGBA", (8, 4)).save(tmp_path / "good", "PNG")
    assert load_stickers(_settings([_item("a", "good")], enabled=False), lambda sha: tmp_path / sha) == []
