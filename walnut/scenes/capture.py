"""촬영 — 컷마다 카운트다운 → 셔터(섬광) → '다음 포즈 준비' → 다음 컷.

셔터 순간의 컷 처리: 카메라 원본 → 거울(capture.mirror) → 필터 → 스티커(이 프레임에서 원본 해상도로
얼굴 검출) → session.add_shot. 원본 컷은 디스크에 저장하지 않는다 (합성본만 share 에서 저장).

셔터 순간 프레임이 없으면(케이블 빠짐) SHUTTER_WAIT 동안 기다려 보고, 그래도 없으면 그 컷을 넘기지 않고
'카메라 연결 중' 을 띄운다. 프레임이 다시 오면 그 컷 카운트다운을 처음부터 한다.
"""

from __future__ import annotations

import logging
import math
import time
from concurrent.futures import Future
from dataclasses import dataclass

import numpy as np
import pygame
from PIL import Image

from .. import sfx, ui
from ..ar import FaceTracker
from ..burst import TimedFrame
from ..compose import cover_crop, round_half_up
from ..filters import apply_filter
from ..remote import fmt_line
from ..session import ShootSession
from ..stickers import Sticker, draw_stickers
from .base import Scene

log = logging.getLogger(__name__)

SHUTTER_WAIT = 0.5   # 셔터 순간 프레임이 없을 때 기다려 보는 시간
FLASH = 0.35         # 하얀 섬광 길이
CAMERA_LOST = "카메라 연결 중"

BURST_BEFORE = 0.7     # 베스트 컷 후보: 셔터 전 이만큼
BURST_AFTER = 0.3      # 셔터 후 이만큼 더 모은다
ANALYZE_TIMEOUT = 1.5  # 분석이 이 시간 안에 안 끝나면 기준 프레임으로 간다

COUNTDOWN, SHUTTER, CAMERA, BETWEEN = "countdown", "shutter", "camera", "between"
COLLECT, ANALYZE = "collect", "analyze"


@dataclass
class Shoot:
    """한 번의 촬영에 쓰는 것: 세션(규칙), 프레임 PNG, 고른 스티커, 거울 여부."""
    session: ShootSession
    frame_png: Image.Image
    sticker: Sticker | None
    mirror: bool


def continue_shoot(app, shoot: Shoot) -> None:
    """컷 사이에 다른 장면(개발자 모드의 베스트 컷 분석 화면)을 거친 뒤 촬영을 잇는다."""
    if shoot.session.capturing_done():
        go_after_capture(app, shoot)
    else:
        app.go(CaptureScene(app, shoot))


def go_after_capture(app, shoot: Shoot) -> None:
    """다 찍은 뒤의 장면: 여분 컷이 있으면 고르기, 없으면 확인."""
    from .pick import PickScene
    from .review import ReviewScene

    nxt = PickScene if shoot.session.extra > 0 else ReviewScene
    app.go(nxt(app, shoot))


# ── 카메라 영상 처리 ────────────────────────────────────────────────
def mirrored(rgb: np.ndarray, on: bool) -> np.ndarray:
    return rgb[:, ::-1] if on else rgb


def crop_to_ratio(rgb: np.ndarray, ratio: float) -> np.ndarray:
    """가운데 기준 cover-crop (합성과 같은 규칙)."""
    h, w = rgb.shape[:2]
    x, y, cw, ch = cover_crop(w, h, ratio, 1.0)
    return rgb[y:y + ch, x:x + cw]


def fit(ratio: float, box: tuple[int, int]) -> tuple[int, int]:
    """비율 ratio(w/h) 를 유지하며 box 안에 들어가는 가장 큰 크기."""
    bw, bh = box
    if bw / bh > ratio:
        return max(1, round_half_up(bh * ratio)), bh
    return bw, max(1, round_half_up(bw / ratio))


def paper_size(ratio: float, box: tuple[int, int], tokens: dict) -> tuple[int, int]:
    """사진 비율 ratio 를 지키며 box 안에 들어가는 인화지 (여백 포함) 의 바깥 크기."""
    b, bb = tokens["print"]["border"], tokens["print"]["border_bottom"]
    iw, ih = fit(ratio, (max(1, box[0] - 2 * b), max(1, box[1] - b - bb)))
    return iw + 2 * b, ih + b + bb


def process_cut(app, raw: np.ndarray, shoot: Shoot) -> Image.Image:
    """셔터 순간: 원본 → 거울 → 필터 → 스티커 (원본 해상도)."""
    rgb = apply_filter(np.ascontiguousarray(mirrored(raw, shoot.mirror)), shoot.session.filter)
    if shoot.sticker is not None:
        faces = app.detector.faces(rgb)
        if faces:
            rgb = draw_stickers(rgb, faces, shoot.sticker)
    return Image.fromarray(rgb)


def cut_thumb(img: Image.Image, ratio: float, box: tuple[int, int]) -> pygame.Surface:
    """컷 사진을 그 컷 비율로 잘라 box 안에 맞춘 썸네일."""
    x, y, cw, ch = cover_crop(img.width, img.height, ratio, 1.0)
    size = fit(ratio, box)
    return ui.pil_to_surface(img.crop((x, y, x + cw, y + ch)).resize(size, Image.Resampling.BILINEAR))


class LiveView:
    """카메라 미리보기: 비율로 자르고 → 줄이고 → 거울 → 필터 → 스티커(떨림 보정).

    미리보기는 축소 프레임에서 얼굴을 찾는다 (최종 컷은 process_cut 이 원본 해상도로 다시 찾는다).
    """

    def __init__(self, app):
        self.app = app
        self.tracker = FaceTracker()
        self._faces: list = []
        self._face_id = -1

    def render(self, ratio: float, box: tuple[int, int], filter_name: str, sticker: Sticker | None,
               mirror: bool) -> pygame.Surface | None:
        frame = self.app.frame
        if frame is None:
            return None
        import cv2

        w, h = fit(ratio, box)
        small = cv2.resize(crop_to_ratio(frame, ratio), (w, h), interpolation=cv2.INTER_AREA)
        small = apply_filter(np.ascontiguousarray(mirrored(small, mirror)), filter_name)
        if sticker is not None and self.app.detector.available:
            if self.app.frame_id != self._face_id:  # 같은 프레임이면 다시 찾지 않는다
                self._face_id = self.app.frame_id
                self._faces = self.tracker.update(self.app.detector.faces(small), time.monotonic())
            small = draw_stickers(small, self._faces, sticker)
        return ui.np_to_surface(small)


def thumb_window(indices, cut: int, size: int = 4) -> list[int]:
    """오른쪽 칸에 보일 컷 번호들. 컷이 size 개보다 많으면 지금 찍을 컷이 맨 아래, 그 위로 최근에 찍은 컷.

    indices 는 화면에 나오는 컷 순서 (보통 0..N-1). cut 이 indices 에 없으면(다 찍음) 마지막 size 개.
    """
    idx = list(indices)
    if len(idx) <= size:
        return idx
    pos = idx.index(cut) if cut in idx else len(idx) - 1
    start = max(0, min(pos - (size - 1), len(idx) - size))
    return idx[start:start + size]


def capture_layout(ratio: float, stage) -> tuple[pygame.Rect, list[pygame.Rect]]:
    """(미리보기 영역, 찍은 사진 칸들). 값은 토큰 layout.capture 에서 읽는다.

    가로: 미리보기는 화면 한가운데 최대한 크게, 칸은 그 오른쪽에 위에서 아래로.
    세로: 미리보기는 위쪽(preview_top), 칸은 아래에 한 줄로 가운데 모아 (thumb_row_bottom).
    칸 Rect 는 사진 비율과 상관없는 '자리' 이고, 그 안에 컷 비율로 맞춘 인화지가 들어간다.
    """
    L = stage.layout("capture")
    preview = pygame.Rect((0, 0), fit(ratio, tuple(L["preview_box"])))
    gap = L["thumb_gap"]
    if stage.orientation == "portrait":
        preview.midtop = (stage.x(stage.base_w / 2, "center"), stage.y(L["preview_top"]))
        row = L["thumb_row"]
        cw, ch = L["thumb_max_w"], row["height"]
        left = (stage.w - (row["slots"] * cw + (row["slots"] - 1) * gap)) // 2
        top = stage.y(stage.base_h - L["thumb_row_bottom"] - ch, "bottom")
        return preview, [pygame.Rect(left + k * (cw + gap), top, cw, ch) for k in range(row["slots"])]
    preview.center = (stage.x(stage.base_w / 2, "center"), stage.y(stage.base_h / 2, "center"))
    right = preview.right + L["thumb_inset"]  # 미리보기 테두리 바깥
    slots = L["thumb_slots"]
    cw = min(L["thumb_max_w"], stage.w - right - 2 * L["thumb_margin"])
    ch = (preview.height - (slots - 1) * gap) // slots
    x = right + (stage.w - right - cw) // 2
    return preview, [pygame.Rect(x, preview.top + k * (ch + gap), cw, ch) for k in range(slots)]


def draw_live(surf: pygame.Surface, live: pygame.Surface | None, center, size: tuple[int, int], ink) -> pygame.Rect:
    """미리보기를 테두리와 함께 그린다. 프레임이 없으면 회색 판 + '카메라 연결 중'."""
    r = pygame.Rect(0, 0, *size)
    r.center = (int(center[0]), int(center[1]))
    ui.rrect(surf, ink, r.inflate(16, 16), 20)
    if live is not None:
        surf.blit(live, live.get_rect(center=r.center))
    else:
        ui.rrect(surf, (60, 64, 76), r, 12)
        ui.text(surf, CAMERA_LOST, 56, ui.WHITE, r.center, face="title")
    return r


# ── 장면 ─────────────────────────────────────────────────────────────
class CaptureScene(Scene):
    layout_name = "capture"

    def __init__(self, app, shoot: Shoot):
        super().__init__(app)
        self.shoot = shoot
        s = shoot.session
        self.countdown = float(s.capture["countdown_sec"])
        self.between = float(s.capture["between_sec"])
        self.retake = bool(s.retake_queue)
        self.total = s.n if self.retake else s.total_shots()
        self.state = COUNTDOWN
        self.remain = self.countdown
        self.wait = 0.0
        self.flash = 0.0
        self._tick: int | None = None
        # 베스트 컷 경로: 셔터 때의 기준 프레임, 대기 중인 분석, 단계별 경과 시간
        self._base: tuple[np.ndarray, float] | None = None
        self._future: Future | None = None
        self._collect_t = 0.0   # 상태 전환용 (dt 누적)
        self._analyze_t = 0.0
        self._t_shutter = 0.0   # 기록용 실제 경과 시간 (perf_counter)
        self._t_submit: float | None = None
        self._n_frames = 0      # 분석에 맡긴 후보 수
        self._cands: list[TimedFrame] = []  # 개발자 모드(all)에서만: 분석 화면에 보일 후보
        self._left = False
        self.live = LiveView(app)
        self._thumbs: dict[int, tuple[tuple, pygame.Surface]] = {}

    # ---- 진행 ----
    def _start_countdown(self) -> None:
        self.state, self.remain, self._tick = COUNTDOWN, self.countdown, None

    def _shutter(self) -> None:
        frame = self.app.frame
        if frame is None:
            self.state, self.wait = SHUTTER, 0.0  # 잠깐 끊긴 것일 수 있다 — 조금 기다려 본다
            return
        self._take(frame)

    def _analysis_on(self) -> bool:
        """베스트 컷 · 스마트 구도 경로를 쓰는가. 분석기가 없거나 모델이 없으면 꺼진 것과 같다."""
        a = self.app.analyzer
        cfg = self.app.cfg
        return a is not None and a.available and (cfg.burst or cfg.smart_crop)

    def _show_on(self) -> bool:
        """개발자 모드(--dev-mode-all): 컷마다 베스트 컷 분석 화면을 보여 준다."""
        return self.app.cfg.dev == "all"

    def _take(self, raw: np.ndarray) -> None:
        s = self.shoot.session
        if not self._analysis_on():
            cut = s.next_cut()
            s.add_shot(process_cut(self.app, raw, self.shoot))
            sfx.play("shutter")
            self.flash = FLASH
            if self._show_on():  # 분석기를 쓸 수 없다 — 조용히 넘어가지 않고 분석 화면에서 알린다
                self._show(cut, [], time.monotonic(), None, "error")
                return
            self._next(False)
            return
        # 소리 · 섬광은 셔터 때 한 번만. 기준 프레임은 분석이 실패해도 쓸 수 있게 쥐고 있는다
        sfx.play("shutter")
        self.flash = FLASH
        self._base = (raw, time.monotonic())
        self._collect_t = self._analyze_t = 0.0
        self._t_shutter, self._t_submit, self._n_frames = time.perf_counter(), None, 0
        if self.app.cfg.burst:
            self.state = COLLECT
        else:  # smart_crop 만: 기준 프레임 한 장을 분석한다
            self._submit([TimedFrame(self._base[1], raw)])

    def _next(self, camera_check: bool) -> None:
        """컷 하나를 넣은 뒤: 끝이면 다음 장면, 아니면 다음 컷 준비."""
        s = self.shoot.session
        if s.capturing_done():
            self._done()
        elif camera_check and self.app.frame is None:
            self.state = CAMERA  # 수집 중에 카메라가 끊겼다 — 기존 '카메라 연결 중' 흐름으로
        elif self.between > 0:
            self.state, self.remain = BETWEEN, self.between
        else:
            self._start_countdown()

    def _submit(self, frames: list[TimedFrame]) -> None:
        t = self._base[1]
        self._t_submit, self._n_frames = time.perf_counter(), len(frames)
        self._cands = list(frames) if self._show_on() else []
        try:
            self._future = self.app.analyzer.submit(frames, t, bool(self.shoot.mirror))
        except Exception as exc:
            log.warning("분석을 맡기지 못해 기준 프레임을 씁니다: %s", exc)
            self._finish_base("error")
            return
        self.state = ANALYZE

    def _collect(self) -> None:
        t = self._base[1]
        frames = self.app.camera.frames_between(t - BURST_BEFORE, t + BURST_AFTER)
        if not frames:
            self._finish_base("no_candidates")
            return
        self._submit(frames)

    def _analyzing(self) -> None:
        fut = self._future
        if fut is None:
            self._finish_base("error")
            return
        if fut.done():
            self._future = None
            try:  # 취소 · 예외 · 모양이 이상한 결과 모두 기준 프레임으로
                res = fut.result()
                raw, faces = res.raw, res.faces
                reason, fallback = str(res.info["reason"]), bool(res.info["fallback_used"])
                n = len(res.info["candidates"])
            except Exception as exc:
                log.warning("베스트 컷 분석 오류로 기준 프레임을 씁니다: %s", exc)
                self._finish_base("error")
                return
            self._finish(raw, faces, reason, fallback, n, res.info)
        elif self._analyze_t >= ANALYZE_TIMEOUT:
            fut.cancel()
            self._future = None  # 늦게 끝난 결과가 다른 컷에 붙지 않게 놓아 준다
            log.warning("베스트 컷 분석이 %.1f초 안에 끝나지 않아 기준 프레임을 씁니다", ANALYZE_TIMEOUT)
            self._finish_base("timeout")

    def _finish_base(self, reason: str) -> None:
        self._finish(self._base[0], None, reason, True, self._n_frames)

    def _finish(self, raw: np.ndarray, faces, reason: str, fallback: bool, candidates: int,
                info: dict | None = None) -> None:
        s = self.shoot.session
        cut, shutter_t = s.next_cut(), self._base[1]
        now = time.perf_counter()
        sub = self._t_submit if self._t_submit is not None else now  # 맡기기 전에 끝났으면 수집만 잰 것
        collect_ms = (sub - self._t_shutter) * 1000.0
        analyze_ms = (now - sub) * 1000.0
        self._base = None
        s.add_shot(process_cut(self.app, raw, self.shoot), faces)
        self.app.capture_log.write({
            "type": "cut", "collect_ms": round(collect_ms, 1), "analyze_ms": round(analyze_ms, 1),
            "total_ms": round(collect_ms + analyze_ms, 1), "candidates": int(candidates),
            "reason": reason, "fallback_used": bool(fallback)})
        if self._show_on():
            frames, self._cands = self._cands, []
            self._show(cut, frames, shutter_t, info, reason)
            return
        self._next(True)

    def _show(self, cut: int, frames: list[TimedFrame], shutter_t: float, info: dict | None, reason: str) -> None:
        """개발자 모드: 방금 넣은 컷의 베스트 컷 분석 화면으로. 끝나면 continue_shoot 이 촬영을 잇는다."""
        from .burst_show import BurstShowScene, ShowData

        app, shoot = self.app, self.shoot
        data = ShowData(frames, shutter_t, info, reason, shoot.session.ratio_for_shot(cut), bool(shoot.mirror), cut)
        app.go(BurstShowScene(app, data, on_done=lambda: continue_shoot(app, shoot)))

    def exit(self) -> None:
        """장면을 떠난다 — 대기 중인 분석은 버린다. 늦게 끝난 결과는 어디에도 붙지 않는다."""
        self._left = True
        fut, self._future = self._future, None
        self._base = None
        self._cands = []
        if fut is not None:
            fut.cancel()

    def _done(self) -> None:
        go_after_capture(self.app, self.shoot)

    def update(self, dt: float) -> None:
        super().update(dt)
        if self._left:
            return
        self.flash = max(0.0, self.flash - dt)
        if self.state == COUNTDOWN:
            self.remain -= dt
            n = math.ceil(self.remain)
            if self.remain > 0 and n != self._tick:
                sfx.play("tick")
                self._tick = n
            if self.remain <= 0:
                self._shutter()
        elif self.state == SHUTTER:
            self.wait += dt
            if self.app.frame is not None:
                self._take(self.app.frame)
            elif self.wait >= SHUTTER_WAIT:
                log.warning("셔터 순간 카메라 프레임이 없어 컷 %d 을 미룹니다", self.shoot.session.next_cut() + 1)
                self.state = CAMERA
        elif self.state == COLLECT:
            self._collect_t += dt
            if self._collect_t >= BURST_AFTER:
                self._collect()
        elif self.state == ANALYZE:
            self._analyze_t += dt
            self._analyzing()
        elif self.state == CAMERA:
            if self.app.frame is not None:
                log.info("카메라 프레임이 돌아와 컷 %d 카운트다운을 다시 시작", self.shoot.session.next_cut() + 1)
                self._start_countdown()
        elif self.state == BETWEEN:
            self.remain -= dt
            if self.remain <= 0:
                self._start_countdown()

    def skip(self) -> None:
        """F2 — 즉시 셔터."""
        if self.state in (COUNTDOWN, BETWEEN):
            self._shutter()

    # ---- 표시 ----
    def done_count(self) -> int:
        s = self.shoot.session
        return s.n - len(s.retake_queue) if self.retake else len(s.shots)

    def message(self) -> str:
        if self.state == CAMERA:
            return CAMERA_LOST
        if self.state == BETWEEN:
            return "다음 포즈 준비"
        return ""

    def remote_state(self) -> str:
        if self.state == COUNTDOWN:
            left = max(0, math.ceil(self.remain * 10 - 1e-6))
        elif self.state == BETWEEN:
            left = -1
        elif self.state == CAMERA:
            left = round_half_up(self.countdown * 10)  # 프레임이 오면 처음부터
        else:
            left = 0
        return fmt_line("C", self.done_count(), self.total, left, round_half_up(self.countdown * 10))

    def _thumb(self, i: int, box: tuple[int, int]) -> pygame.Surface | None:
        s = self.shoot.session
        if i >= len(s.shots) or i in s.retake_queue:
            return None
        img = s.shots[i]
        key = (id(img), box)
        hit = self._thumbs.get(i)
        if hit is None or hit[0] != key:
            hit = (key, cut_thumb(img, s.ratio_for_shot(i), box))
            self._thumbs[i] = hit
        return hit[1]

    def draw(self, surf: pygame.Surface) -> None:
        s = self.shoot.session
        st, roles = self.app.stage, self.app.theme.roles
        L = st.layout("capture")
        portrait = st.orientation == "portrait"
        cut = s.next_cut()
        ratio = s.ratio_for_shot(min(cut, max(0, s.total_shots() - 1)))
        preview, cells = capture_layout(ratio, st)
        live = self.live.render(ratio, preview.size, s.filter, self.shoot.sticker, self.shoot.mirror)
        r = draw_live(surf, live, preview.center, preview.size, roles["line"])

        # '컷 k / N' — 가로는 미리보기 왼쪽 칸 가운데, 세로는 맨 위
        label = f"컷 {min(cut + 1, s.total_shots())} / {self.total}"
        if portrait:
            side = st.w // 2
            ui.text(surf, label, st.size("headline"), roles["title"], (side, st.y(L["label_y"])), face="number",
                    max_width=st.w - 2 * L["side_pad"])
            spot, width = r.center, r.width  # 숫자 · 안내는 미리보기 위에 올린다
        else:
            side = r.x / 2
            width = int(r.x - L["side_pad"])
            ui.text(surf, label, st.size("headline"), roles["title"], (side, st.y(L["label_y"])), face="number",
                    max_width=width)
            spot = (side, r.centery)
        self._draw_status(surf, st, roles, spot, width, portrait)
        self._draw_thumbs(surf, st, roles, cells, portrait)

        if self.flash > 0:
            white = pygame.Surface((st.w, st.h), pygame.SRCALPHA)
            white.fill((255, 255, 255, int(255 * self.flash / FLASH)))
            surf.blit(white, (0, 0))

    def _draw_status(self, surf, st, roles, spot, width: int, portrait: bool) -> None:
        """카운트다운 숫자와 '다음 포즈 준비' · '카메라 연결 중' 안내."""
        fx = st.tokens["color"]["fixed"]
        paper = ui.hex_rgb(fx["paper"])
        if self.state == COUNTDOWN:
            ui.text(surf, str(max(1, math.ceil(self.remain))), st.size("countdown"), roles["action"], spot,
                    face="number", shadow=paper)
        elif self.state == BETWEEN:
            if portrait:  # 미리보기 위라 인화지색 알약 위에 짙은 글씨
                size, step = st.size("button"), st.tokens["space"]["step"]
                ink = ui.hex_rgb(fx["dark_ink"])
                text = ui.font(size, "title", self.message()).render(self.message(), True, ink)
                pill = text.get_rect().inflate(2 * step[3], 2 * step[0])
                pill.center = (int(spot[0]), int(spot[1]))
                ui.rrect(surf, paper, pill, pill.height // 2)
                surf.blit(text, text.get_rect(center=pill.center))
            else:
                ui.text(surf, self.message(), st.size("headline"), roles["title"], spot, face="title", max_width=width)
        elif self.state == CAMERA and not portrait:  # 세로는 미리보기 안 글자로 충분하다
            ui.text(surf, self.message(), st.size("headline"), roles["title"], spot, face="title", max_width=width)

    def _draw_thumbs(self, surf: pygame.Surface, st, roles, cells: list[pygame.Rect], portrait: bool) -> None:
        """찍은 컷 칸. 컷이 4개보다 많으면 지금 찍을 컷과 최근에 찍은 컷만 보인다."""
        s = self.shoot.session
        L = st.layout("capture")
        tk = st.tokens
        b, bb = tk["print"]["border"], tk["print"]["border_bottom"]
        cut = s.next_cut()
        indices = range(s.n) if self.retake else range(self.total)
        win = thumb_window(indices, cut, len(cells))
        dx = (len(cells) - len(win)) * (cells[0].width + L["thumb_gap"]) // 2 if portrait else 0  # 모자라면 가운데로
        for cell, i in zip(cells, win):
            cell = cell.move(dx, 0)
            ratio = s.ratio_for_shot(i)
            card = fit(ratio, (cell.width - 2 * b, cell.height - b - bb))
            card = (card[0] + 2 * b, card[1] + b + bb)
            slot = pygame.Rect((0, 0), card)
            if portrait:  # 세로 줄은 위에 맞춘다
                slot.midtop = cell.midtop
            else:
                slot.center = cell.center
            th = self._thumb(i, (card[0] - 2 * b, card[1] - b - bb))
            if th is not None:
                paper = ui.print_card(surf, th, slot.center, tk, roles)
                ui.number_badge(surf, (paper.x + L["badge_at"], paper.y + L["badge_at"]), L["badge_r"], i + 1, roles,
                                kind="cut")
            else:  # 아직 안 찍은 자리 — 점선 대신 옅은 테두리, 지금 찍을 칸은 선명하게
                nxt = i == cut
                line = roles["line"]
                alpha = 1.0 if nxt else tk["color"]["alpha"]["empty_slot"]
                box = pygame.Surface(slot.size, pygame.SRCALPHA)
                ui.rrect(box, line, box.get_rect(), tk["space"]["radius"]["card"], tk["touch"]["line_px"])
                box.fill((255, 255, 255, int(255 * alpha + 0.5)), special_flags=pygame.BLEND_RGBA_MULT)
                surf.blit(box, slot)
                ui.text(surf, str(i + 1), st.size("button"), roles["title"] if nxt else roles["hint"], slot.center,
                        face="number", ink=True)
