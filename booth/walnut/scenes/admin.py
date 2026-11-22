"""관리자 패널 (ESC) — 장면 위에 덮는 창. 열려 있는 동안 장면은 입력을 받지 않는다.

    pin        PIN 6자리 다이얼 (PinGate: 5번 틀리면 60초 잠금)
    panel      상태 + [지금 동기화] [번들 파일 가져오기] [연결 해제(재페어링)], 머리에 [처음 화면으로] [다음 단계로]
    limited    페어링은 됐지만 PIN 이 없을 때 (번들 전): [번들 파일 가져오기] 만
    quit_only  페어링 전: 종료 안내만
    local      연결 없이 사용 중 (PIN 없음): [연결 코드 입력으로], 머리에 [처음 화면으로] [다음 단계로]
Q 를 3초 안에 두 번 누르면 종료 (pin 상태에서는 안 된다). 연결 해제도 한 번 더 눌러야 한다.
키보드 없는 터치 설치를 위해 머리에 [종료](pin 제외, 두 번 확인) · [닫기](모든 모드)를 둔다.
배치는 토큰 layout.admin, 시안 screens/parts.js adminScreen, 웹 AdminPanel.tsx.
"""

from __future__ import annotations

import math
import time
from typing import Callable

import pygame

from .. import ui
from ..printer import ReceiptPrinter
from ..remote import fmt_line
from ..touch import HitMap
from .dial import DigitDial

PIN_LEN = 6
CONFIRM_SEC = 3.0
LABELS = {"sync": "지금 동기화", "import": "번들 파일 가져오기", "unpair": "연결 해제(재페어링)",
          "home": "처음 화면으로", "next": "다음 단계로", "pair": "연결 코드 입력으로",
          "print_test": "시험 인쇄"}
HEAD = ("home", "next")  # 머리 줄에 놓이는 버튼 (buttons() 의 뒤쪽)
QUIT_ASK = "한 번 더 누르면 종료"
HINT_TOUCH = {"pin": "숫자 패드로 넣고 확인을 눌러 주세요", "panel": "버튼을 눌러 주세요",
              "limited": "버튼을 눌러 주세요", "quit_only": "버튼을 눌러 주세요", "local": "버튼을 눌러 주세요"}


def printer_status(printer) -> str:
    """관리자 패널 상태 줄의 프린터 칸."""
    if not isinstance(printer, ReceiptPrinter):
        return "더미 (파일로 저장)"
    if printer.off():
        return "꺼짐"
    port = printer.port()
    return f"{port} 연결됨 · 대기 {printer.pending()}" if port else "연결 안 됨"


class AdminPanel:
    def __init__(self, app, clock: Callable[[], float] = time.monotonic):
        self.app = app
        self._clock = clock
        if app.device is None and getattr(app, "local", False):
            self.mode = "local"
        elif app.device is None:
            self.mode = "quit_only"
        elif app.pin_gate is None:
            self.mode = "limited"
        else:
            self.mode = "pin"
        self.hits = HitMap()
        self.rects: dict[str, pygame.Rect] = {}  # 마지막으로 그린 버튼 · 패널 영역 (시험 · 스크린샷용)
        self.dial = DigitDial(PIN_LEN, masked=True)
        self.dial.on_submit = self._check_pin
        self.message = ""
        self.cursor = 0
        self._confirm: tuple[str, float] | None = None

    def hit(self, rect, action: Callable[[], None]) -> None:
        """탭을 받을 영역을 등록한다 (그릴 때마다 다시)."""
        self.hits.add(pygame.Rect(rect), action)

    # ---- 상태 ----

    def buttons(self) -> list[str]:
        if self.mode == "panel":
            return ["sync", *self._printer_buttons(), "import", "unpair", "home", "next"]
        if self.mode == "limited":
            return ["import"]
        if self.mode == "local":  # 개발자 모드는 서버가 없어 연결 코드 화면으로 갈 일이 없다
            return [*self._printer_buttons(), *(["home", "next"] if self.app.cfg.dev else ["pair", "home", "next"])]
        return []

    def _printer_buttons(self) -> list[str]:
        """시험 인쇄는 실제 영수증 프린터일 때만 (더미는 파일로 쌓을 뿐이다)."""
        return ["print_test"] if isinstance(self.app.printer, ReceiptPrinter) else []

    def enabled(self, name: str) -> bool:
        """처음 화면으로 · 다음 단계로는 손님 흐름이 대기 장면일 때 쓸 수 없다."""
        if name in HEAD:
            return not getattr(self.app.scene, "idle", False)
        return True

    def quit_label(self) -> str:
        return QUIT_ASK if self._confirm and self._confirm[0] == "quit" else "종료"

    def _locked_message(self, secs: float) -> str:
        return f"PIN 을 5번 틀려 잠겼어요 — {math.ceil(secs)}초 뒤 다시 시도하세요"

    def _check_pin(self, code: str) -> None:
        gate = self.app.pin_gate
        self.dial.reset()
        if gate is None:
            return
        if gate.locked_for() > 0:
            self.message = self._locked_message(gate.locked_for())
        elif gate.check(code):
            self.mode = "panel"
            self.message = ""
        elif gate.locked_for() > 0:
            self.message = self._locked_message(gate.locked_for())
        else:
            self.message = "PIN 이 맞지 않아요"

    def _confirmed(self, name: str) -> bool:
        """같은 동작을 3초 안에 두 번 눌렀는가. 처음이면 기억만 한다."""
        now = self._clock()
        if self._confirm and self._confirm[0] == name and now - self._confirm[1] < CONFIRM_SEC:
            self._confirm = None
            return True
        self._confirm = (name, now)
        return False

    # ---- 입력 ----

    def handle(self, event: pygame.event.Event) -> None:
        if event.type != pygame.KEYDOWN:
            return
        if self.mode == "pin":
            self.dial.handle(event)
            return
        k = event.key
        btns = self.buttons()
        if k == pygame.K_q:
            self._quit()
        elif k in (pygame.K_LEFT, pygame.K_UP) and btns:
            self._move(-1)
        elif k in (pygame.K_RIGHT, pygame.K_DOWN) and btns:
            self._move(1)
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) and btns:
            self._activate(btns[self.cursor])

    def _move(self, d: int) -> None:
        """커서를 옮긴다 — 쓸 수 없는 버튼은 건너뛴다."""
        btns = self.buttons()
        for _ in range(len(btns)):
            self.cursor = (self.cursor + d) % len(btns)
            if self.enabled(btns[self.cursor]):
                break
        self._confirm = None

    def _quit(self) -> None:
        if self._confirmed("quit"):
            self.app.running = False

    def _tap(self, name: str) -> None:
        """탭: 커서를 그 버튼으로 옮기고 키 Enter 와 같이 누른다."""
        btns = self.buttons()
        if name in btns:
            if not self.enabled(name):
                return
            self.cursor = btns.index(name)
        self._activate(name)

    def _activate(self, name: str) -> None:
        app = self.app
        if name == "close":
            app.close_admin()
        elif name == "quit":
            self._quit()
        elif name in HEAD:
            if not self.enabled(name):
                return
            app.close_admin()
            app._safe(app.home if name == "home" else app.scene.skip)
        elif name == "sync":
            if app.sync is not None:
                app.sync.sync_now()
                self.message = "동기화를 요청했어요"
            else:
                self.message = "서버가 설정되지 않았어요"
        elif name == "import":
            from .import_zip import ImportZipScene

            app.close_admin()
            app.go(ImportZipScene(app))
        elif name == "pair":
            app.leave_local()
        elif name == "print_test":
            ok = isinstance(app.printer, ReceiptPrinter) and app.printer.print_test()
            self.message = "시험 인쇄를 보냈어요" if ok else "프린터를 찾지 못했어요"
        elif name == "unpair":
            if self._confirmed("unpair"):
                app.unpair("연결을 해제했어요. 새 코드로 다시 연결하세요")

    def update(self, dt: float) -> None:
        gate = self.app.pin_gate
        if self.mode == "pin" and gate is not None and gate.locked_for() > 0:
            self.message = self._locked_message(gate.locked_for())

    def remote_state(self) -> str:
        if self.mode == "pin":
            return fmt_line("N", self.dial.entered(), PIN_LEN)
        return "-"

    # ---- 그리기 ----

    def _status_lines(self) -> list[str]:
        app = self.app
        b, dev, sync = app.bundle, app.device, app.sync
        lines = [f"행사  {(b.event_name if b else '') or (dev.event_name if dev else '-')}",
                 f"번들  {'v' + str(b.version) if b else '없음'}"]
        if sync is None:
            lines.append("동기화  서버 없음")
        else:
            ago = "아직 없음" if sync.last_ok_at is None else f"{int(time.monotonic() - sync.last_ok_at)}초 전"
            lines.append(f"마지막 동기화  {ago}")
            lines.append(f"서버  {'연결됨' if sync.online else '연결 안 됨'}  {sync.last_error}".rstrip())
        up = f"업로드 대기  {app.uploader.pending()}건"
        if app.uploader.last_error:
            up += f"  ({app.uploader.last_error[:40]})"
        lines.append(up)
        cam = f"연결됨 {app.camera.fps:.0f}fps" if app.camera.connected else "끊김"
        lines.append(f"화면 {app.fps:.0f}fps   카메라 {cam}")
        if app.cfg.remote_port.lower() == "off":
            rem = "꺼짐"
        else:
            rem = "연결됨" if app.remote.connected else "연결 안 됨"
        lines.append(f"리모컨  {rem}")
        lines.append(f"프린터  {printer_status(app.printer)}")
        sample = app.sample_status()
        if sample:
            lines.append(sample)
        return lines

    def draw(self, surf: pygame.Surface) -> None:
        app = self.app
        st, roles, tk = app.stage, app.theme.roles, app.stage.tokens
        L = st.layout("admin")
        pw, ph = L["panel"]
        padx, pady = L["pad"]
        key_mode = app.input_kind == "key"
        self.rects = {}

        # 장면을 가리는 막 + 배경색 카드 (숫자 패드 선이 보이려면 밝은 면이어야 한다)
        scrim = pygame.Surface(surf.get_size(), pygame.SRCALPHA)
        scrim.fill((*roles["background_bottom"][:3], int(255 * tk["color"]["alpha"]["overlay"] + 0.5)))
        surf.blit(scrim, (0, 0))
        box = pygame.Rect(0, 0, pw, ph)
        box.center = (st.x(st.base_w / 2, "center"), st.y(st.base_h / 2, "center"))
        self.rects["panel"] = box
        sh = tk["print"]["shadow"]
        shadow, pad = ui._shadow((pw, ph), sh["blur"], int(255 * tk["color"]["alpha"]["print_shadow"] + 0.5),
                                 ui.hex_rgb(tk["color"]["fixed"]["dark_ink"]))
        surf.blit(shadow, (box.x - pad, box.y - pad + sh["y"]))
        ui.panel(surf, box, tuple(roles["background_top"][:3]), radius=L["panel_radius"], border=roles["line"],
                 border_w=tk["touch"]["line_px"])

        title = ui.text(surf, "관리자", st.size("headline"), roles["title"], (box.x + padx, box.y + pady),
                        anchor="topleft", face="title")
        self._draw_head(surf, box, L, title.right, key_mode)

        label = st.size("label")
        inner = pw - 2 * padx
        if self.mode == "pin":
            ui.text(surf, "PIN 6자리를 넣어 주세요", st.size("body"), roles["title"],
                    (box.centerx, box.y + L["pin_y"]), max_width=inner)
            self.dial.show_arrows = key_mode
            self.dial.draw(surf, st, roles, self.hit, "admin", origin=box.topleft)
        elif self.mode == "quit_only":
            ui.text(surf, "페어링 전에는 관리자 기능이 없어요", st.size("body"), roles["title"],
                    (box.centerx, box.y + L["pin_y"]), max_width=inner)
        else:
            if self.mode == "panel":
                lines = self._status_lines()
            elif self.mode == "local":
                lines = [app.local_note()] + [x for x in (app.sample_status(),) if x]
            else:
                lines = ["번들이 아직 없어요 — PIN 은 번들을 받은 뒤 생겨요"]
            y = box.y + pady + L["text_step"]
            for line in lines:
                ui.text(surf, line, label, roles["title"], (box.x + padx, y), anchor="topleft", max_width=inner)
                y += L["status_step"] if st.orientation == "portrait" else L["line_step"]
            self._draw_actions(surf, box, L, label, key_mode)

        if self.message:
            ui.text(surf, self.message, label, roles["title"], (box.centerx, box.bottom - L["message_bottom"]),
                    face="title", max_width=inner)
        hint = HINT_TOUCH[self.mode]
        if key_mode:
            hint = "Q 두 번  종료    ESC  닫기    F5  처음으로    F2  건너뛰기"
            if self.mode == "pin":
                hint = "↑↓ 숫자  ←→ 자리  Enter 확인    ESC  닫기"
            elif self.mode == "quit_only":
                hint = "Q 두 번  종료    ESC  닫기"
            elif self.mode == "limited":
                hint = "Enter 가져오기    Q 두 번  종료    ESC  닫기"
            elif self.mode == "local":
                hint = "←→ 고르기  Enter 확인    Q 두 번  종료    ESC  닫기"
        if self.mode != "pin" and self._confirm and self._confirm[0] == "quit":
            hint = "한 번 더 Q 를 누르면 종료합니다" if key_mode else "종료를 한 번 더 누르면 끝나요"
        ui.text(surf, hint, label, roles["hint"], (box.centerx, box.bottom - L["hint_bottom"]), face="label", max_width=inner)

    def _button(self, surf, name: str, rect, label: str, *, kind: str, focused: bool = False, enabled: bool = True) -> None:
        st = self.app.stage
        self.rects[name] = pygame.Rect(rect)
        ui.action_button(surf, rect, label, self.app.theme.roles, kind=kind, focused=focused, enabled=enabled,
                         ring=st.tokens["touch"]["focus_ring_px"], size=st.size("label"), face="label")
        self.hit(rect, lambda n=name: self._tap(n))

    def _draw_head(self, surf, box, L, title_right: int, key_mode: bool) -> None:
        """머리 줄 오른쪽 — [처음 화면으로] [다음 단계로] (panel) [종료] (pin 제외) [닫기]. 오른쪽 끝에서 왼쪽으로 놓는다."""
        st = self.app.stage
        tk = st.tokens
        padx, pady = L["pad"]
        h = L["button_h"]
        names = ([n for n in HEAD if n in self.buttons()]) + (["quit"] if self.mode != "pin" else []) + ["close"]
        labels = {n: (self.quit_label() if n == "quit" else "닫기" if n == "close" else LABELS[n]) for n in names}
        pad = tk["space"]["step"][3]
        widths = {n: ui.font(st.size("label"), "label", labels[n]).size(labels[n])[0] + 2 * pad for n in names}
        gap = L["button_gap"]
        avail = box.width - 2 * padx - (title_right - (box.x + padx)) - gap * 2
        need = sum(widths.values()) + gap * (len(names) - 1)
        if need > avail:  # 좁으면 글자가 줄어들도록 비율로 줄인다
            f = (avail - gap * (len(names) - 1)) / sum(widths.values())
            widths = {n: int(w * f) for n, w in widths.items()}
        x = box.right - padx
        btns = self.buttons()
        for n in reversed(names):
            r = pygame.Rect(0, 0, widths[n], h)
            r.topright = (x, box.y + pady)
            x = r.x - gap
            kind = "action" if n == "quit" and self._confirm and self._confirm[0] == "quit" else "line"
            focused = key_mode and n in btns and btns.index(n) == self.cursor
            self._button(surf, n, r, labels[n], kind=kind, focused=focused, enabled=self.enabled(n))

    def _draw_actions(self, surf, box, L, label: int, key_mode: bool) -> None:
        """아래 버튼 줄 — 가로는 한 줄, 세로는 폭을 채워 쌓는다."""
        st = self.app.stage
        padx = L["pad"][0]
        h, gap = L["button_h"], L["button_gap"]
        names = [n for n in self.buttons() if n not in HEAD]
        labels = {n: ("한 번 더 누르면 해제" if n == "unpair" and self._confirm and self._confirm[0] == "unpair" else LABELS[n])
                  for n in names}
        pad = st.tokens["space"]["step"][3]
        btns = self.buttons()
        portrait = st.orientation == "portrait"
        x = box.x + padx
        y = box.bottom - L["buttons_bottom"] + (h - (len(names) * h + (len(names) - 1) * gap) if portrait else 0)
        inner = box.width - 2 * padx
        text_w = {n: ui.font(label, "label", labels[n]).size(labels[n])[0] for n in names}
        if not portrait and names:
            # 한 줄이 패널 안쪽을 넘으면 (시험 인쇄 버튼 · '한 번 더 누르면 해제') 버튼 안 여백 → 간격 순으로 줄인다
            over = sum(text_w.values()) + 2 * pad * len(names) + gap * (len(names) - 1) - inner
            if over > 0:
                pad = max(12, pad - math.ceil(over / (2 * len(names))))
                over = sum(text_w.values()) + 2 * pad * len(names) + gap * (len(names) - 1) - inner
                if over > 0 and len(names) > 1:
                    gap = max(8, gap - math.ceil(over / (len(names) - 1)))
        for n in names:
            w = inner if portrait else text_w[n] + 2 * pad
            r = pygame.Rect(x, y, w, h)
            asking = n == "unpair" and self._confirm and self._confirm[0] == "unpair"
            self._button(surf, n, r, labels[n], kind="action" if asking else "line",
                         focused=key_mode and btns.index(n) == self.cursor)
            if portrait:
                y += h + gap
            else:
                x = r.right + gap
