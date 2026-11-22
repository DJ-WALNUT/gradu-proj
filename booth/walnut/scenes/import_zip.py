"""비상용 번들 zip 가져오기 — 서버에 닿지 않는 현장에서 USB 로 번들을 넣는다.

찾는 곳: data/import/, ~/Downloads, 이동식 드라이브 루트. 최신 파일부터 최대 20개.
서명(HMAC)·해시·행사·버전 검증은 BundleStore.import_zip 이 한다. 성공하면 바로 적용된다.
배치는 토큰 layout.import_zip, 시안 screens/import_zip.js, 웹 ImportZip.tsx. 줄을 탭하면 Enter 와 같다.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pygame

from .. import ui
from ..bundle import ZipImportError
from .base import Scene, is_key

log = logging.getLogger(__name__)

MAX_FILES = 20
VISIBLE = 10  # 한 화면에 보이는 줄
DRIVE_REMOVABLE = 2

REASONS = {
    "bad_zip": "zip 파일이 손상됐거나 번들 파일이 아니에요",
    "bad_signature": "서명이 맞지 않아요 (다른 부스용이거나 바뀐 파일)",
    "other_event": "다른 행사의 번들이에요",
    "older_version": "지금 쓰는 번들보다 오래된 버전이에요",
    "sha_mismatch": "번들 안의 파일이 손상됐어요",
}


MAC_VOLUMES = Path("/Volumes")


def _is_system_volume(p: Path) -> bool:
    """macOS 의 시스템 디스크 (/Volumes/Macintosh HD 는 / 를 가리킨다)."""
    try:
        return p.resolve() == Path("/").resolve()
    except OSError:
        return True


def _mac_volumes() -> list[Path]:
    """macOS 에 꽂힌 USB 등 — /Volumes 아래 폴더 중 시스템 디스크와 숨김 항목을 뺀 것."""
    try:
        items = sorted(MAC_VOLUMES.iterdir())
    except OSError:
        return []
    return [p for p in items if not p.name.startswith(".") and p.is_dir() and not _is_system_volume(p)]


def removable_roots() -> list[Path]:
    """이동식 드라이브(USB) 루트. Windows 는 드라이브 종류로, macOS 는 /Volumes 로 찾는다. 그 밖의 OS 는 빈 목록."""
    if sys.platform == "darwin":
        return _mac_volumes()
    if sys.platform != "win32":
        return []
    try:
        import ctypes
        import string

        k32 = ctypes.windll.kernel32
        mask = k32.GetLogicalDrives()
        roots = []
        for i, letter in enumerate(string.ascii_uppercase):
            if mask >> i & 1:
                root = f"{letter}:\\"
                if k32.GetDriveTypeW(ctypes.c_wchar_p(root)) == DRIVE_REMOVABLE:
                    roots.append(Path(root))
        return roots
    except Exception:
        log.exception("이동식 드라이브 목록을 읽지 못함")
        return []


def default_dirs(data_dir: Path) -> list[Path]:
    return [Path(data_dir) / "import", Path.home() / "Downloads", *removable_roots()]


def find_zips(dirs: list[Path]) -> list[Path]:
    """dirs 바로 아래의 *.zip, 최신순 최대 20개."""
    found: dict[Path, float] = {}
    for d in dirs:
        try:
            for p in Path(d).glob("*.zip"):
                try:
                    if p.is_file():
                        found[p.resolve()] = p.stat().st_mtime
                except OSError:
                    pass
        except OSError:
            pass  # 없는 폴더, 빠진 USB
    return sorted(found, key=lambda p: -found[p])[:MAX_FILES]


class ImportZipScene(Scene):
    layout_name = "import_zip"

    def __init__(self, app):
        super().__init__(app)
        self.files = find_zips(app.import_dirs())
        self.sel = 0  # len(files) 는 '돌아가기'
        self.message = ""
        self.ok = False
        self.done = False
        self.rows: list[pygame.Rect] = []  # 마지막으로 그린 줄 영역 (시험 · 스크린샷용)

    def handle(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        n = len(self.files) + 1
        if self.done:
            if is_key(event, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
                self.app.home()
            return
        if event.key == pygame.K_UP:
            self.sel = (self.sel - 1) % n
        elif event.key == pygame.K_DOWN:
            self.sel = (self.sel + 1) % n
        elif is_key(event, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.activate()

    def activate(self) -> None:
        """Enter — 고른 줄을 가져오고, '돌아가기' 면 처음 화면으로."""
        if self.sel >= len(self.files):
            self.app.home()
        else:
            self._import(self.files[self.sel])

    def tap_item(self, i: int) -> None:
        """줄 탭 — 고르고 Enter 처럼 누른다. 끝난 뒤에는 어느 줄이든 처음 화면으로."""
        if self.done:
            self.app.home()
            return
        self.sel = max(0, min(i, len(self.files)))
        self.activate()

    def _import(self, path: Path) -> None:
        try:
            v = self.app.import_zip(path)
        except ZipImportError as e:
            log.warning("zip 가져오기 거절 (%s): %s", e.reason, path)
            self.message = REASONS.get(e.reason, f"가져올 수 없어요 ({e.reason})")
            return
        except OSError as e:
            log.warning("zip 을 읽지 못함: %s", e)
            self.message = "파일을 읽을 수 없어요"
            return
        self.ok = self.done = True
        self.message = (f"번들 v{v} 을 적용했어요 — Enter 를 누르면 처음 화면으로" if self.app.input_kind == "key"
                        else f"번들 v{v} 을 적용했어요 — 화면을 누르면 처음 화면으로")

    def draw(self, surf: pygame.Surface) -> None:
        app = self.app
        st, roles, tk = app.stage, app.theme.roles, app.stage.tokens
        L = st.layout("import_zip")
        key_mode = app.input_kind == "key"
        x0 = st.x(L["list_x"], "left")
        ui.text(surf, "번들 파일 가져오기", st.size("title_l"), roles["title"],
                (x0, st.y(L["title_pos"][1], "top")), anchor="midleft", face="title", max_width=st.w - 2 * x0)
        ui.text(surf, "data/import · 다운로드 · USB 의 zip 파일", st.size("label"), roles["hint"],
                (st.x(L["sub_pos"][0], "left"), st.y(L["sub_pos"][1], "top")), anchor="midleft", max_width=st.w - 2 * x0)
        rows = [str(p) for p in self.files] + ["돌아가기"]
        vis, step, rh = L["visible"], L["row_step"], L["row_h"]
        y0 = st.y(L["list_top"], "top")
        if not self.files:
            ui.text(surf, "zip 파일을 찾지 못했어요", st.size("body"), roles["title"],
                    (st.x(L["empty_x"], "left"), y0 + rh // 2), anchor="midleft")
            y0 += step
        start = max(0, min(self.sel - vis // 2, len(rows) - vis))  # 길면 커서 둘레만
        self.rows = []
        if self.done:  # 끝난 뒤에는 화면 어디를 눌러도 처음 화면으로 (줄 hit 이 위에 쌓여도 같은 동작)
            self.hit(st.rect(), self.app.home)
        radius = tk["space"]["radius"]["card"]
        pad = tk["space"]["step"][3]
        w = st.w - 2 * x0
        for k, i in enumerate(range(start, min(len(rows), start + vis))):
            r = pygame.Rect(x0, y0 + k * step, w, rh)
            on = i == self.sel and not self.done
            if on:
                ui.panel(surf, r, roles["action"], radius=radius)
                if key_mode:
                    g = tk["space"]["step"][0] + tk["touch"]["focus_ring_px"]
                    ui.rrect(surf, roles["line"], r.inflate(2 * g, 2 * g), radius + g, tk["touch"]["focus_ring_px"])
            ui.text(surf, rows[i], st.size("caption"), roles["on_action"] if on else roles["title"],
                    (r.x + pad, r.centery), anchor="midleft", max_width=r.width - 2 * pad)
            self.rows.append(r)
            self.hit(r, lambda i=i: self.tap_item(i))
        cx = st.x(st.base_w / 2, "center")
        my = st.y(st.base_h - L["message_bottom"], "bottom")
        if self.message:
            ui.text(surf, self.message, st.size("button"), roles["title"], (cx, my),
                    face="title", max_width=st.w - 2 * x0)
        else:
            hint = "↑↓ 고르기   Enter 가져오기" if key_mode else "가져올 파일을 눌러 주세요"
            ui.text(surf, hint, st.size("label"), roles["hint"], (cx, my), max_width=st.w - 2 * x0)
