"""공유 — 완료 처리(저장·업로드 대기열)와 QR 화면.

토큰은 부스가 먼저 만든다. QR 은 업로드를 기다리지 않고 바로 띄우고, 사진은 outbox 로 백그라운드 업로드.
qr_enabled 가 꺼졌거나 서버가 없으면 '부스 PC 에 저장되었어요'.
qr_screen_sec 뒤 · Enter · 화면 아무 데나 탭 → 인쇄가 켜졌으면 매수 고르기, 아니면 대기 화면.
탭은 곧 장면을 떠나므로 이 장면의 타이머(t)는 되돌릴 필요가 없다.
배치는 토큰 layout.share (시안 screens/share.js, 웹 Share.tsx 와 같다).
"""

from __future__ import annotations

import hashlib
import logging
import math
from datetime import datetime

import pygame
import qrcode
from PIL import Image

from .. import sfx, ui
from ..compose import save_jpeg
from ..remote import fmt_line
from ..uploader import DONE, NO_SERVER, RETRYING, UPLOADING, new_token
from .base import Scene, fit_surface, is_key
from .capture import paper_size

log = logging.getLogger(__name__)

ASK = "휴대폰으로 찍어 사진을 받으세요"
SAVED = "부스 PC 에 저장되었어요"
STATUS = {  # 업로드 상태 줄 (웹 부스 Share.tsx 와 같은 문구)
    UPLOADING: "사진을 올리는 중이에요 — 지금 찍어도 곧 열려요",
    DONE: "사진이 올라갔어요",
    RETRYING: "사진을 다시 보내는 중이에요 — QR 은 그대로 쓸 수 있어요",
    NO_SERVER: "서버에 연결되지 않아 사진은 이 부스에만 남아요",
}


def finish(app, collage: Image.Image, shoot=None) -> None:
    """QR 받기: 토큰 → data/collage/<행사>_<월일-시분초>_<토큰>.jpg → (켜져 있으면) 업로드 대기열 → 공유 화면.

    파일 이름에 토큰이 있으므로 로그 · 촬영 기록에는 이름 대신 촬영 id 와 합성본 해시만 남긴다."""
    token = new_token()
    path = app.cfg.data_dir / "collage" / f"{app.bundle.event_id}_{datetime.now():%m%d-%H%M%S}_{token}.jpg"
    save_jpeg(collage, path)
    log.info("합성본 저장 (촬영 %s)", getattr(app, "shoot_id", None) or "-")
    _log_result(app, collage, path, shoot)
    online = bool(app.bundle.settings["share"]["qr_enabled"] and app.cfg.server_url and app.device is not None)
    url = None
    if online:
        app.uploader.enqueue(token, path)
        # 사진이 올라가는 서버 (페어링한 주소). SERVER_URL 이 그 뒤 바뀌었어도 QR 은 사진이 있는 곳을 가리킨다
        url = f"{app.device.server_url.rstrip('/')}/p/{token}"
    sfx.play("clear")
    app.go(ShareScene(app, collage, token, url))


def _log_result(app, collage: Image.Image, path, shoot) -> None:
    """result 줄: 재촬영 횟수 · 합성 시간 · 합성본 해시 (파일 이름 아님). 실패해도 공유는 이어진다."""
    if app.capture_log.path is None:
        return
    try:
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        s = shoot.session if shoot is not None else None
        ms = shoot.compose_ms if shoot is not None else None
        app.capture_log.write({
            "type": "result", "retakes": s.retakes if s else None,
            "compose_ms": None if ms is None else round(ms, 1),
            "cuts": s.n if s else None, "collage": [collage.width, collage.height], "collage_sha256": sha,
            "display_fps": round(float(app.fps), 1), "camera_fps": round(float(app.camera.fps), 1)})
    except Exception as e:
        log.warning("result 기록을 남기지 못했습니다: %s", e)


def qr_surface(url: str, color, size: int) -> pygame.Surface:
    qr = qrcode.QRCode(border=2, box_size=12, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color=tuple(color), back_color=(255, 255, 255)).get_image()
    return ui.pil_to_surface(img.convert("RGB").resize((size, size), Image.Resampling.NEAREST))


class ShareScene(Scene):
    layout_name = "share"

    def __init__(self, app, collage: Image.Image, token: str, url: str | None):
        super().__init__(app)
        self.collage = collage
        self.token = token
        self.url = url
        self.total = int(app.bundle.settings["share"]["qr_screen_sec"])
        st, tk = app.stage, app.stage.tokens
        L = st.layout("share")
        pw, ph = paper_size(collage.width / collage.height, tuple(L["preview_box"]), tk)
        self.paper = pygame.Rect(0, 0, pw, ph)
        self.paper.center = (st.x(L["preview_center"][0], "center"), st.y(L["preview_center"][1], "center"))
        b, bb = tk["print"]["border"], tk["print"]["border_bottom"]
        self.preview = fit_surface(collage, (pw - 2 * b, ph - b - bb))
        # QR 무늬는 어떤 행사 색이든 찍히게 고정 짙은 잉크
        self.qr = qr_surface(url, ui.hex_rgb(tk["color"]["fixed"]["dark_ink"]), L["qr_size"]) if url else None

    def handle(self, event: pygame.event.Event) -> None:
        if is_key(event, pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE):
            self.skip()

    def skip(self) -> None:
        pr = self.app.bundle.settings["print"]
        if pr["enabled"] and self.app.printer.available():
            from .print_copies import PrintCopiesScene

            self.app.go(PrintCopiesScene(self.app, self.collage, self.token, url=self.url))
        else:
            self.app.home()

    def update(self, dt: float) -> None:
        super().update(dt)
        if self.t >= self.total:
            self.skip()

    def left(self) -> int:
        return max(0, math.ceil(self.total - self.t))

    def message(self) -> str:
        return ASK if self.url else SAVED

    def remote_state(self) -> str:
        return fmt_line("S", self.left(), self.total, self.app.uploader.state(self.token))

    def _status(self, surf: pygame.Surface, pos, anchor: str, max_w: int) -> None:
        """업로드 상태 줄 — 올리는 중은 점 셋, 다 올라가면 동그라미 체크가 글자 앞에 붙는다. 길면 줄을 나눈다."""
        app = self.app
        st, roles = app.stage, app.theme.roles
        state = app.uploader.state(self.token)
        size = st.size("label")
        icon = size if state in (UPLOADING, DONE) else 0
        color = roles["title"] if state == DONE else roles["hint"]
        lines = ui.wrap_lines(STATUS[state], size, max_w - icon, "body", lines=3)
        step_y = round(size * 1.25)
        imgs = [ui.font(size, "body", t).render(t, True, color) for t in lines]
        w = icon + max(i.get_width() for i in imgs)
        r = pygame.Rect(0, 0, w, step_y * len(imgs))
        setattr(r, anchor, (int(pos[0]), int(pos[1])))
        for k, img in enumerate(imgs):
            x = r.x + icon if anchor == "midleft" else r.centerx - img.get_width() // 2 + icon // 2
            surf.blit(img, (x, r.y + k * step_y + (step_y - img.get_height()) // 2))
        c = (r.x + size // 2 - 4, r.y + step_y // 2)
        if state == DONE:
            ui.circle(surf, roles["line"], c, size * 0.45, st.tokens["touch"]["line_px"])
            pygame.draw.lines(surf, roles["title"], False,
                              [(c[0] - size * 0.17, c[1]), (c[0] - size * 0.04, c[1] + size * 0.13), (c[0] + size * 0.2, c[1] - size * 0.14)],
                              st.tokens["touch"]["line_px"])
        elif state == UPLOADING:
            for k in range(3):
                hop = max(0.0, math.sin(self.t * 5 - k * 0.9)) * size * 0.3
                ui.circle(surf, roles["action"] if k == 1 else roles["line"], (r.x + size // 4 + k * size // 3, c[1] + size // 8 - hop), size * 0.11)

    def draw(self, surf: pygame.Surface) -> None:
        app = self.app
        st, roles, tk = app.stage, app.theme.roles, app.stage.tokens
        L = st.layout("share")
        portrait = st.orientation == "portrait"
        low = "bottom" if portrait else "center"
        key = app.input_kind == "key"
        self.hit(surf.get_rect(), self.skip)  # 화면 아무 데나 누르면 다음으로

        ui.print_card(surf, self.preview, self.paper.center, tk, roles)
        qx, qy = st.x(L["qr_center"][0], "center"), st.y(L["qr_center"][1], low)
        cx = st.x(st.base_w / 2, "center")
        if self.qr is not None:
            ring = tk["touch"]["focus_ring_px"]
            card = pygame.Rect(0, 0, *(L["qr_size"] + 2 * L["qr_pad"] + 2 * ring,) * 2)
            card.center = (qx, qy)
            paper = ui.hex_rgb(tk["color"]["fixed"]["paper"])
            ui.rrect(surf, roles["line"], card, tk["space"]["radius"]["card"] * 2)
            ui.rrect(surf, paper, card.inflate(-2 * ring, -2 * ring), tk["space"]["radius"]["card"] * 2 - ring)
            surf.blit(self.qr, self.qr.get_rect(center=card.center))
            if portrait:
                # 세로 — QR 오른쪽에 안내 · 상태를 위에서부터 (카드 가운데 높이)
                x = st.x(L["text_x"], "center")
                size = st.size("button")
                lines = ui.wrap_lines(self.message(), size, L["message_max_w"], "title")
                step_y = round(size * 1.15)
                y = qy - st.size("label") // 2 - (len(lines) * step_y) // 2 + step_y // 2
                for k, line in enumerate(lines):
                    ui.text(surf, line, size, roles["title"], (x, y + k * step_y), anchor="midleft", face="title")
                self._status(surf, (x, y + (len(lines) - 1) * step_y + st.size("label") * 2 + tk["space"]["step"][2]), "midleft",
                             L["message_max_w"])
            else:
                ui.text(surf, self.message(), st.size("button"), roles["title"], (qx, st.y(L["message_y"], "center")),
                        face="title", max_width=L["message_max_w"])
                self._status(surf, (qx, st.y(L["status_y"], "center")), "center", L["message_max_w"])
        else:
            x = cx if portrait else st.x(L["qr_center"][0], "center")
            y = qy if portrait else st.y(L["message_solo_y"], "center")
            ui.text(surf, self.message(), st.size("headline"), roles["title"], (x, y), face="title", max_width=L["solo_max_w"])

        info = f"{self.left()}초 뒤 처음 화면으로  ·  " + ("버튼을 누르면 바로 넘어가요" if key else "화면을 누르면 바로 넘어가요")
        ui.text(surf, info, st.size("caption"), roles["hint"], (cx if portrait else qx, st.y(L["info_y"], low)),
                max_width=L["info_max_w"])
