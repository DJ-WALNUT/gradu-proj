"""행사 테마: 색, 문구, 행사 글꼴 대체."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pygame

from walnut.settings import clamp_settings
from walnut.theme import Theme

SHA = "a" * 64


def _bundle(branding: dict) -> SimpleNamespace:
    # clamp 를 거치지 않은 값도 Theme 가 스스로 방어하는지 보려고 settings 를 직접 만든다
    s = clamp_settings({})
    s["branding"].update(branding)
    return SimpleNamespace(settings=s)


def test_no_bundle_uses_defaults():
    t = Theme.from_bundle(None, lambda sha: None)
    assert t.title == "포토부스" and t.font_path is None and t.logo is None
    assert t.colors["primary"] == (0x1b, 0x25, 0x50)


def test_theme_colors_and_privacy_ttl():
    b = _bundle({"colors": {"primary": "#zzzzzz", "accent": "#ff0000", "bg_top": 12, "bg_bottom": "#00ff00"},
                 "privacy_text": "{ttl}시간 뒤 삭제"})
    t = Theme.from_bundle(b, lambda sha: None)
    assert t.colors["primary"] == (0x1b, 0x25, 0x50)  # 잘못된 값 → 기본색
    assert t.colors["accent"] == (255, 0, 0)
    assert t.colors["bg_top"] == (0xff, 0xf8, 0xf9)
    assert t.colors["bg_bottom"] == (0, 255, 0)
    assert t.privacy_text == "72시간 뒤 삭제"


def test_bad_font_asset_falls_back(tmp_path):
    empty = tmp_path / "empty"
    empty.write_bytes(b"")
    junk = tmp_path / "junk"
    junk.write_bytes(b"not a font" * 50)
    for p in (empty, junk, tmp_path / "missing"):
        t = Theme.from_bundle(_bundle({"font_asset": SHA}), lambda sha, p=p: p)
        assert t.font_path is None
    # sha 형식이 아니라 asset_path 가 예외를 던져도 기본값
    def bad(sha):
        raise ValueError("bad_sha")
    assert Theme.from_bundle(_bundle({"font_asset": SHA, "logo_asset": SHA}), bad).font_path is None


def test_font_without_hangul_falls_back(tmp_path):
    latin = os.path.join(os.path.dirname(pygame.__file__), "freesansbold.ttf")
    t = Theme.from_bundle(_bundle({"font_asset": SHA}), lambda sha: latin)
    assert t.font_path is None


def test_hangul_font_is_used():
    from walnut import fonts
    p = fonts.FILES["body"]
    t = Theme.from_bundle(_bundle({"font_asset": SHA}), lambda sha: p)
    assert t.font_path == p


def test_logo_loaded_and_bad_logo_ignored(tmp_path):
    from PIL import Image
    good = tmp_path / "logo"
    Image.new("RGBA", (40, 20), (255, 0, 0, 255)).save(good, format="PNG")
    t = Theme.from_bundle(_bundle({"logo_asset": SHA}), lambda sha: good)
    assert t.logo is not None and t.logo.get_size() == (40, 20)
    bad = tmp_path / "bad"
    bad.write_bytes(b"xx")
    assert Theme.from_bundle(_bundle({"logo_asset": SHA}), lambda sha: bad).logo is None


def test_theme_roles_come_from_resolve_roles():
    th = Theme.from_bundle(None, lambda s: None)
    assert set(th.roles) >= {"background_top", "background_bottom", "title", "hint", "action", "on_action", "credit"}
    assert all(v is None or len(v) == 3 for v in th.roles.values())
    assert th.tokens["color"]["roles"].keys() == th.roles.keys()
