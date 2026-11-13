"""행사 준비 중 — 페어링은 됐지만 아직 번들이 없다 (게시 전이거나 첫 번들을 받는 중).

번들이 준비되면 App 이 이 장면에서 바로 대기 화면으로 바꾼다 (idle = True). 탭에는 반응하지 않는다.
배치는 토큰 layout.waiting, 시안 screens/waiting.js, 웹 Waiting.tsx.
"""

from __future__ import annotations

import math

import pygame

from .. import ui
from .base import Scene

ARC_STEP = 4  # 반원 각도 단위 (도)
SPIN_SEC = 2.1  # 반원이 한 바퀴 도는 시간 (motion.duration_ms 700 × 3)


class WaitingScene(Scene):
    idle = True
    layout_name = "waiting"

    def __init__(self, app):
        super().__init__(app)
        self._cache: dict = {}

    def status(self) -> str:
        sync = self.app.sync
        if sync is None:
            if self.app.input_kind == "touch":
                return "서버 주소가 없어요 — 왼쪽 위를 길게 눌러 관리자 패널에서 번들 파일을 가져오세요"
            return "서버 주소가 없어요 — 관리자 패널(ESC)에서 번들 파일을 가져오세요"
        if sync.not_published:
            return "관리자 웹에서 행사를 게시하면 시작돼요"
        if not sync.online and sync.last_error:
            return "서버에 연결할 수 없어요 — 다시 시도하는 중"
        return "행사 정보를 받는 중…"

    def remote_state(self) -> str:
        return "W"

    def _ring(self, surf: pygame.Surface, center: tuple[int, int], r: int, width: int) -> None:
        """종이색 고리 위를 강조색 반원이 천천히 돈다. 각도를 ARC_STEP 도 단위로 나눠 한 번 만든 그림을 다시 쓴다."""
        roles = self.app.theme.roles
        paper = ui.hex_rgb(self.app.theme.tokens["color"]["fixed"]["paper"])
        outer = r + width // 2
        deg = int((360 * (self.t / SPIN_SEC)) // ARC_STEP * ARC_STEP) % 360
        key = (outer, width, tuple(roles["action"][:3]), paper, deg)
        img = self._cache.get(key)
        if img is None:
            k = ui.SUPERSAMPLE
            big = pygame.Surface(((outer * 2 + 2) * k,) * 2, pygame.SRCALPHA)
            big.fill((*paper, 0))  # 투명 가장자리가 검게 번지지 않게 종이색으로 깐다
            pygame.draw.circle(big, paper, (big.get_width() // 2, big.get_height() // 2), outer * k, width * k)
            start = -math.radians(deg)
            pygame.draw.arc(big, (*roles["action"][:3], 255), pygame.Rect(k, k, outer * 2 * k, outer * 2 * k),
                            start, start + math.pi, width * k)
            img = pygame.transform.smoothscale(big, (outer * 2 + 2, outer * 2 + 2))
            if len(self._cache) > 360 // ARC_STEP + 4:
                self._cache.clear()
            self._cache[key] = img
        surf.blit(img, img.get_rect(center=center))

    def draw(self, surf: pygame.Surface) -> None:
        app = self.app
        st, roles = app.stage, app.theme.roles
        L = st.layout("waiting")
        cx = st.x(st.base_w / 2, "center")
        self._ring(surf, (st.x(L["ring_center"][0], "center"), st.y(L["ring_center"][1], "center")),
                   L["ring_r"], L["ring_width"])
        ui.text(surf, "행사 준비 중", st.size("hero"), roles["title"], (cx, st.y(L["title_y"], "center")), face="title",
                max_width=L["status_max_w"])
        dev = app.device
        if dev is not None:
            ui.text(surf, dev.event_name, st.size("button"), roles["title"], (cx, st.y(L["event_y"], "center")),
                    max_width=L["event_max_w"])
        size = st.size("body")
        y = st.y(L["status_y"], "center")
        for i, line in enumerate(ui.wrap_lines(self.status(), size, L["status_max_w"], "body", lines=3)):
            ui.text(surf, line, size, roles["hint"], (cx, y + int(i * size * 1.4)))
