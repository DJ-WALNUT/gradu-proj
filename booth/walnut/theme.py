"""행사 테마 — 번들 branding 에서 색·문구·글꼴·로고를 꺼낸다.

무엇이 잘못돼도 화면은 뜬다: 잘못된 색은 기본색, 열리지 않거나 한글이 없는 글꼴은 내장 Paperlogy,
열리지 않는 로고는 없음.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pygame

from .booth_design import load as load_tokens, resolve_roles
from .settings import DEFAULTS

log = logging.getLogger(__name__)

_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_DEF = DEFAULTS["branding"]


def _rgb(v: object, default: str) -> tuple[int, int, int]:
    s = v if isinstance(v, str) and _HEX.fullmatch(v) else default
    return int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16)


def _str(v: object, default: str) -> str:
    return v if isinstance(v, str) else default


_FONT_MAGIC = (b"\x00\x01\x00\x00", b"OTTO", b"true", b"ttcf")  # TrueType · OpenType · 글꼴 모음


def font_ok(path: Path) -> bool:
    """pygame 으로 열리고 '가' 글리프가 있는 글꼴인가."""
    try:
        # 글꼴 머리말이 아닌 파일은 FreeType 에 넘기지 않는다 (pygame 재초기화 뒤 쓰레기 파일에서 죽은 적이 있다)
        with open(path, "rb") as f:
            if f.read(4) not in _FONT_MAGIC:
                return False
        import pygame.freetype

        if not pygame.freetype.get_init():
            pygame.freetype.init()
        f = pygame.freetype.Font(str(path), 24)
        return f.get_metrics("가")[0] is not None
    except Exception:
        return False


def _asset(asset_path: Callable[[str], Path], sha: object) -> Path | None:
    if not isinstance(sha, str) or not sha:
        return None
    try:
        p = asset_path(sha)
    except Exception:
        return None
    return Path(p) if p and Path(p).is_file() else None


def _load_logo(path: Path) -> pygame.Surface | None:
    try:
        from PIL import Image

        from .ui import pil_to_surface

        with Image.open(path) as im:
            return pil_to_surface(im)
    except Exception as exc:
        log.warning("로고를 열 수 없어 빼고 그립니다: %s", exc)
        return None


@dataclass
class Theme:
    title: str
    subtitle: str
    start_text: str
    colors: dict[str, tuple[int, int, int]]
    font_path: Path | None
    logo: pygame.Surface | None
    privacy_text: str
    roles: dict[str, tuple[int, int, int] | None]  # 색 역할 (디자인 토큰, 행사 색에서 계산)
    tokens: dict  # 디자인 토큰 전체

    @classmethod
    def from_bundle(cls, bundle, asset_path: Callable[[str], Path]) -> "Theme":
        """bundle 이 None 이면 기본 테마. asset_path(sha) → 에셋 파일 경로."""
        settings = bundle.settings if bundle is not None else DEFAULTS
        b = settings.get("branding") or {}
        cols = b.get("colors") if isinstance(b.get("colors"), dict) else {}
        colors = {k: _rgb(cols.get(k), d) for k, d in _DEF["colors"].items()}

        tokens = load_tokens()
        event = {k: "#%02x%02x%02x" % colors[k] for k in ("primary", "accent", "bg_top", "bg_bottom")}
        roles = {k: (_rgb(v, "#000000") if v is not None else None) for k, v in resolve_roles(tokens, event).items()}

        font_path = _asset(asset_path, b.get("font_asset"))
        if font_path is not None and not font_ok(font_path):
            log.warning("행사 글꼴을 쓸 수 없어 (열리지 않거나 한글 없음) 내장 글꼴로 그립니다")
            font_path = None

        logo_path = _asset(asset_path, b.get("logo_asset"))
        logo = _load_logo(logo_path) if logo_path is not None else None

        ttl = (settings.get("share") or {}).get("ttl_hours", DEFAULTS["share"]["ttl_hours"])
        privacy = _str(b.get("privacy_text"), _DEF["privacy_text"]).replace("{ttl}", str(ttl))
        return cls(
            title=_str(b.get("title"), _DEF["title"]),
            subtitle=_str(b.get("subtitle"), _DEF["subtitle"]),
            start_text=_str(b.get("start_text"), _DEF["start_text"]),
            colors=colors,
            font_path=font_path,
            logo=logo,
            privacy_text=privacy,
            roles=roles,
            tokens=tokens,
        )
