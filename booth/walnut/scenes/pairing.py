"""페어링 — 관리자 웹에서 받은 8자리 코드로 이 부스를 행사에 연결한다.

요청은 스레드에서 보낸다 (서버가 느려도 화면이 멈추지 않게). 결과는 update() 에서 메인 루프가 받는다.
"""

from __future__ import annotations

import logging
import threading

import pygame

from ..version import app_version

from .. import ui
from ..api import Rejected, Unreachable, pair
from ..remote import fmt_line
from .base import Scene, is_key
from .dial import DigitDial

log = logging.getLogger(__name__)

CODE_LEN = 8
NO_SERVER = ".env 의 SERVER_URL 을 설정하세요"
BAD_CODE = "코드가 맞지 않거나 만료되었어요"
UNREACHABLE = "서버에 연결할 수 없어요"


GUIDE = "관리자 웹에서 받은 8자리 페어링 코드를 넣어 주세요"
BUSY = "연결하는 중…"
HINT_KEY = "↑↓ 숫자  ←→ 자리  Enter 확인"
HINT_TOUCH = "숫자 패드로 넣고 확인을 눌러 주세요"
LOCAL_LABEL = "연결 없이 시작"
HINT_LOCAL = "    Tab 연결 없이 시작"


class PairingScene(Scene):
    """배치는 토큰 layout.pairing · dial, 시안 screens/pairing.js, 웹 Pairing.tsx."""

    layout_name = "pairing"

    def __init__(self, app, message: str = ""):
        super().__init__(app)
        self.dial = DigitDial(CODE_LEN)
        self.dial.on_submit = self._submit
        self.dial.locked = lambda: self.busy or not self.server_url  # 연결 중 · 서버 없음에는 패드도 무시
        self.server_url = app.cfg.server_url
        self.message = message or ("" if self.server_url else NO_SERVER)
        self.busy = False
        self._result: tuple | None = None  # 스레드가 채운다

    def _submit(self, code: str) -> None:
        if self.busy or not self.server_url:
            return
        self.busy = True
        self.message = BUSY
        threading.Thread(target=self._pair, args=(code,), name="pair", daemon=True).start()

    def _pair(self, code: str) -> None:
        try:
            self._result = ("ok", pair(self.server_url, code, app_version()))
        except Rejected as e:
            log.warning("페어링 거절: %s", e)
            self._result = ("fail", BAD_CODE)
        except Unreachable as e:
            log.warning("페어링 실패: %s", e)
            self._result = ("fail", UNREACHABLE)
        except Exception:
            log.exception("페어링 중 예상 밖 오류")
            self._result = ("fail", UNREACHABLE)

    def start_local(self) -> None:
        """연결 없이 시작 — 서버 주소가 없어도 된다. 연결 요청 중에는 무시한다."""
        if not self.busy:
            self.app.start_local()

    def local_rect(self) -> pygame.Rect:
        """'연결 없이 시작' 버튼 — 오른쪽 위 구석."""
        st = self.app.stage
        pad = st.tokens["space"]["step"]
        size = st.size("label")
        w = ui.font(size, "label", LOCAL_LABEL).size(LOCAL_LABEL)[0] + 2 * pad[3]
        r = pygame.Rect(0, 0, w, st.layout("admin")["button_h"])
        r.topright = (st.w - pad[4], pad[4])
        return r

    def handle(self, event: pygame.event.Event) -> None:
        if is_key(event, pygame.K_TAB):
            self.start_local()
            return
        if self.busy or not self.server_url:
            return
        self.dial.handle(event)

    def update(self, dt: float) -> None:
        super().update(dt)
        result, self._result = self._result, None
        if result is None:
            return
        self.busy = False
        if result[0] == "ok":
            log.info("페어링 완료: 행사 %s", result[1].event_name)
            self.app.on_paired(result[1])
        else:
            self.message = result[1]
            self.dial.reset()

    def remote_state(self) -> str:
        return fmt_line("N", self.dial.entered(), CODE_LEN)

    def hint(self) -> str:
        return HINT_KEY + HINT_LOCAL if self.app.input_kind == "key" else HINT_TOUCH

    def draw(self, surf: pygame.Surface) -> None:
        app = self.app
        st, roles = app.stage, app.theme.roles
        L = st.layout("pairing")
        tk = st.tokens
        cx = st.x(st.base_w / 2, "center")
        wide = L["server_max_w"]
        ui.text(surf, "부스 연결", st.size("title_xl"), roles["title"], (cx, st.y(L["title_y"], "top")), face="title", max_width=wide)
        ui.text(surf, GUIDE, st.size("body"), roles["title"], (cx, st.y(L["guide_y"], "top")), max_width=wide)
        ui.text(surf, f"서버  {self.server_url or '(없음)'}", st.size("label"), roles["hint"],
                (cx, st.y(L["server_y"], "top")), max_width=wide)
        local = self.local_rect()  # 숫자 패드보다 먼저 등록한다 (패드 12칸이 탭 목록의 맨 뒤)
        ui.action_button(surf, local, LOCAL_LABEL, roles, kind="line", enabled=not self.busy,
                         ring=tk["touch"]["focus_ring_px"], size=st.size("label"), face="label")
        self.hit(local, self.start_local)
        self.dial.show_arrows = app.input_kind == "key"
        self.dial.draw(surf, st, roles, self.hit, "pairing")
        if self.message:
            self._draw_message(surf, st, roles, (cx, st.y(L["message_y"], "center")), wide)
        size = st.size("body")
        cap = st.h - tk["credit"]["bottom"] - st.size("credit") - tk["space"]["step"][1] - size // 2  # 표기 위로만
        y = min(st.y(st.base_h - L["hint_bottom"], "bottom"), cap)
        ui.text(surf, self.hint(), size, roles["hint"], (cx, y), face="label", max_width=st.w - 2 * tk["space"]["step"][4])

    def _draw_message(self, surf, st, roles, center, max_w: int) -> None:
        """오류는 강조색 느낌표 배지 + 제목색 글자, 진행 안내는 글자만 (시안 parts.js message)."""
        size = st.size("button")
        if self.busy:
            ui.text(surf, self.message, size, roles["title"], center, face="title", max_width=max_w)
            return
        br = round(size * 0.65)
        gap = st.tokens["space"]["step"][1]
        text_w = min(ui.font(size, "title", self.message).size(self.message)[0], max_w - 2 * br - gap)
        x0 = center[0] - (2 * br + gap + text_w) / 2
        ui.badge(surf, (x0 + br, center[1]), br, roles["action"], "!", round(size * 0.8), roles["on_action"], face="title")
        ui.text(surf, self.message, size, roles["title"], (x0 + 2 * br + gap, center[1]), anchor="midleft", face="title",
                max_width=text_w)
