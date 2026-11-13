"""부스 앱 본체 — 창 · 카메라 · 장면 전환 · 번들 적용 · 연결 해제 · 관리자 단축키.

관리자 키 (어느 화면에서든)
  ESC   관리자 패널 열기/닫기 (PIN 입력부터)
  F2    지금 단계 건너뛰기
  F5    처음 화면으로
  패널 안에서 Q 두 번 = 종료

스레드: 동기화(SyncWorker)·업로드(Uploader)·카메라·리모컨은 각자 스레드에서 돈다. 화면과 상태 변경은
메인 루프(step)만 한다 — 연결 해제처럼 스레드에서 오는 일은 플래그로 받아 step 에서 처리한다.
requests.Session 은 스레드끼리 나눠 쓰지 않는다 (동기화용·업로드용 BoothApi 를 따로 만든다).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import pygame
from PIL import Image

from . import default_bundle, fonts, sfx, ui
from .api import BoothApi
from .bundle import Bundle, BundleStore
from .burst import CaptureLog, FrameRing
from .camera import Camera, FakeCamera
from .config import Config
from .device import Device, DeviceStore
from .pin import PinGate
from .printer import DummyPrinter
from .remote import Remote
from .session import ShootSession
from .scenes.admin import AdminPanel
from .scenes.base import Scene
from .scenes.capture import CaptureScene, Shoot
from .scenes.choose import ChooseScene, shoot_options
from .scenes.idle import IdleScene
from .scenes.import_zip import default_dirs
from .scenes.pairing import PairingScene
from .scenes.waiting import WaitingScene
from .stickers import load_stickers
from .sync import SyncWorker
from .booth_design import credit_visible, load as load_tokens
from .stage import geometry as stage_geometry
from .theme import Theme
from .touch import Gesture, TouchTracker
from .uploader import Uploader
from .vision import FaceDetector

log = logging.getLogger(__name__)

REVOKED_MESSAGE = "이 부스는 연결이 해제되었습니다"
LOCAL_NOTE = "연결 없이 사용 중 — 사진은 이 PC 에만 저장돼요"
DEV_NOTE = "개발자 모드 — 연결 없이 사용 중, 사진은 이 PC 에만 저장돼요"
DEV_NO_BURST = "개발자 모드 — 버스트샷 꺼짐: 얼굴 모델을 불러오지 못했어요 (models 폴더를 지우고 다시 실행해 주세요)"
DEV_SETTINGS = {"capture": {"countdown_sec": 4}}  # 개발자 모드의 기본 번들에 덮어쓰는 값
TAP_GUARD_SEC = 0.3  # 장면이 바뀐 뒤 이 시간 안의 탭은 버린다 (연타 · 손가락을 댄 채 넘어간 경우)
SHUTDOWN_JOIN_SEC = 0.5  # 종료 때 동기화 스레드를 기다리는 최대 시간


class App:
    def __init__(self, cfg: Config, no_camera: bool = False, windowed: bool = False,
                 display_size: tuple[int, int] | None = None):
        self.cfg = cfg
        # SCALED 는 기본이 '가장 가까운 픽셀' 확대라 모니터가 1920×1080 이 아니면 곡선이 깨진다. 부드럽게 늘린다.
        os.environ.setdefault("SDL_RENDER_SCALE_QUALITY", "linear")
        pygame.init()
        sfx.init()
        ui.clear_caches()  # 앞서 pygame.quit 된 글꼴이 남아 있지 않게
        fonts.clear_caches()
        flags = pygame.SCALED
        if cfg.fullscreen and not windowed:
            flags |= pygame.FULLSCREEN
        if display_size is None:
            try:
                display_size = tuple(pygame.display.get_desktop_sizes()[0])
            except (pygame.error, IndexError):
                display_size = (1920, 1080)
        # 방향 · 논리 크기는 모니터 화면비로 정한다 (웹 부스와 같은 계산)
        tokens = load_tokens()
        self.stage = stage_geometry(display_size[0], display_size[1], tokens, cfg.orientation)
        self.screen = pygame.display.set_mode((self.stage.w, self.stage.h), flags)
        pygame.display.set_caption("호두네사진관")
        pygame.mouse.set_visible(windowed)
        self.clock = pygame.time.Clock()
        self.time_fn = time.monotonic  # 시험에서 바꿔 끼운다 (탭 방지 시간)
        self.input_kind = "key"  # 마지막 입력의 종류: key · touch
        self._went_at = float("-inf")
        hotspot = self.stage.layout("idle")["admin_hotspot"]
        self.tracker = TouchTracker(tokens["touch"], pygame.Rect(0, 0, hotspot, hotspot),
                                    clock=lambda: self.time_fn())
        self.fps = 0.0

        data = cfg.data_dir
        for d in (data, data / "collage", data / "import"):
            d.mkdir(parents=True, exist_ok=True)
        self.device_store = DeviceStore(data / "device.json")
        # 개발자 모드는 페어링 정보를 읽지 않는다 (data-dev/ 에 남아 있어도)
        self.device: Device | None = None if cfg.dev else self.device_store.load()
        self.store = BundleStore(data)

        self.capture_log = CaptureLog(data / "logs" / "capture_metrics.jsonl" if cfg.capture_log else None)
        if no_camera:
            self.camera = FakeCamera()
        else:
            ring = FrameRing() if cfg.burst else None
            self.camera = Camera(cfg.camera_index, cfg.camera_width, cfg.camera_height, ring=ring)
        self.detector = FaceDetector(cfg.models_dir / "face_landmarker.task")
        # 베스트 컷 · 스마트 구도용 분석기. 둘 다 꺼져 있으면 만들지 않는다 (모델도 불러오지 않는다)
        self.analyzer = None
        if cfg.burst or cfg.smart_crop:
            from .analysis import BurstAnalyzer

            self.analyzer = BurstAnalyzer(cfg.models_dir / "face_landmarker.task")
            self.analyzer.warm()
        self.printer = DummyPrinter(data / "print_spool")
        self.remote = Remote(cfg.remote_port)
        self._remote_title: str | None = None

        # 연결 해제는 동기화·업로드 스레드에서 온다 → 플래그만 세우고 step 이 처리한다
        self._revoked = threading.Event()
        self._sync_gen = 0  # 해제·재페어링으로 버린 옛 동기화 스레드의 알림은 무시한다
        self.uploader = Uploader(data / "outbox", None, on_revoked=self._revoked.set)
        self.sync: SyncWorker | None = None

        self.bundle: Bundle | None = None
        self.local = False  # 연결 없이 사용 (기본 번들). 저장하지 않는다 — 다시 켜면 연결 코드 화면
        self._options: dict[str, list] = {}   # 촬영 흐름: 단계별 선택지
        self._chosen: dict[str, object] = {}  # 촬영 흐름: 단계별로 고른 값
        self.theme = Theme.from_bundle(None, self.store.asset_path)
        self.stickers: list = []
        self.pin_gate: PinGate | None = None
        self._load_bundle(self._current_bundle())
        self._start_network()
        self.uploader.start()

        self.frame = None
        self.frame_id = -1
        self.admin: AdminPanel | None = None
        self.scene: Scene | None = None
        self.running = True
        self._shut = False
        if cfg.dev:
            self.start_local(DEV_SETTINGS)
        else:
            self.home()

    # ── 번들 · 네트워크 ──────────────────────────────────────────────
    def _other_event(self, b: Bundle | None) -> bool:
        """이 기기가 페어링된 행사의 번들이 아닌가 (재페어링 중 옛 동기화가 남긴 것 등)."""
        if b is None or self.device is None or b.event_id == self.device.event_id:
            return False
        log.warning("다른 행사(%s)의 번들 v%s 는 쓰지 않음 (이 기기 행사 %s)", b.event_id, b.version, self.device.event_id)
        return True

    def _current_bundle(self) -> Bundle | None:
        """적용 중인 번들. 다른 행사 것이면 모두 비워 다음 동기화가 새로 받게 한다."""
        if self.device is None:
            return None
        b = self.store.current()
        if self._other_event(b):
            self.store.clear()
            return None
        return b

    def _load_bundle(self, bundle: Bundle | None) -> None:
        """번들에 딸린 것(테마·스티커·PIN)을 모두 다시 만든다."""
        self.bundle = bundle
        self.theme = Theme.from_bundle(bundle, self.store.asset_path)
        ui.set_theme_font(self.theme.font_path)
        self.stickers = load_stickers(bundle.settings, self.store.asset_path) if bundle else []
        pin_hash = bundle.settings["admin"]["pin_hash"] if bundle else ""
        self.pin_gate = PinGate(pin_hash, self.device.bundle_key) if pin_hash and self.device else None

    def _start_network(self) -> None:
        """페어링돼 있고 SERVER_URL 이 있으면 동기화·업로드를 켠다. 없으면 오프라인으로만 돈다."""
        if self.device is None or not self.cfg.server_url:
            self.uploader.set_api(None)
            return
        self.uploader.set_api(BoothApi(self.device))
        self._sync_gen += 1
        gen = self._sync_gen
        self.sync = SyncWorker(BoothApi(self.device), self.store, self._status, self.cfg.sync_interval,
                               on_revoked=lambda: self._on_sync_revoked(gen))
        self.sync.start()

    def _on_sync_revoked(self, gen: int) -> None:
        if gen == self._sync_gen:
            self._revoked.set()

    def _stop_sync(self) -> None:
        old, self.sync = self.sync, None
        self._sync_gen += 1
        if old is not None:  # 요청 도중이면 끝날 때까지 기다리게 되므로 화면을 막지 않게 따로
            threading.Thread(target=old.stop, name="sync-stop", daemon=True).start()

    def _status(self) -> dict:
        """하트비트에 실을 상태 (동기화 스레드에서 부른다)."""
        return {"outbox": self.uploader.pending(), "camera_ok": bool(self.camera.connected),
                "fps": float(f"{self.fps:.1f}"), "remote_ok": bool(self.remote.connected)}

    def _maybe_swap_bundle(self) -> None:
        """받아 둔 새 번들을 대기 계열 장면에서만 적용한다 (촬영 도중엔 보류)."""
        sync = self.sync
        if sync is None or self.scene is None or not self.scene.idle:
            return
        ready = sync.ready_version
        if ready is None or ready <= (self.bundle.version if self.bundle else -1):
            return
        if self._other_event(self.store.peek(ready)):
            self.store.discard(ready)  # 남겨 두면 버전이 겹쳐 새 행사 번들을 받지 못한다
            sync.ready_version = None
            return
        try:
            b = self.store.activate(ready)
        except Exception:
            log.exception("번들 %s 적용 실패", ready)
            sync.ready_version = None
            return
        log.info("새 번들 v%s 적용", b.version)
        self._load_bundle(b)
        self.home()

    def on_paired(self, device: Device) -> None:
        """페어링 성공 (PairingScene 이 메인 루프에서 부른다)."""
        # 지난 페어링에서 못 올린 사진이 새 행사로 올라가지 않게 먼저 옮긴다
        self.uploader.set_api(None)
        n = self.uploader.orphan_all()
        if n:
            log.warning("지난 페어링에서 못 올린 사진 %d장을 outbox/orphaned 로 옮김", n)
        self.device_store.save(device)
        self.device = device
        self.local = False
        self.store.clear()  # 지난 행사 번들이 남아 있으면 쓰지 않는다
        self._load_bundle(None)
        self._stop_sync()
        self._start_network()
        if self.sync is not None:
            self.sync.sync_now()
        self.go(WaitingScene(self))

    def unpair(self, message: str = REVOKED_MESSAGE) -> None:
        """연결 해제 (서버 401 또는 관리자 패널). 못 올린 사진은 outbox/orphaned 로 옮긴다."""
        log.warning("부스 연결 해제: %s", message)
        self.close_admin()
        self.uploader.set_api(None)
        n = self.uploader.orphan_all()
        if n:
            log.warning("못 올린 사진 %d장을 outbox/orphaned 로 옮김", n)
        self._stop_sync()
        self.device_store.clear()
        self.device = None
        self.store.clear()
        self._load_bundle(None)
        self._revoked.clear()
        self.go(PairingScene(self, message=message))

    # ── 연결 없이 사용 ───────────────────────────────────────────────
    def start_local(self, settings_patch: dict | None = None) -> None:
        """페어링 없이 기본 번들로 대기 화면에 선다. 사진은 이 PC 에만 남는다 (QR · 업로드 없음)."""
        default_bundle.install(self.store)
        self._load_bundle(default_bundle.build(settings_patch))
        self.local = True
        log.info("연결 없이 시작 — 기본 번들 사용")
        self.go(IdleScene(self))

    def leave_local(self) -> None:
        """연결 없이 사용을 끝내고 연결 코드 화면으로."""
        self.close_admin()
        self.local = False
        self._load_bundle(None)
        self.go(PairingScene(self))

    def local_note(self) -> str:
        if not self.cfg.dev:
            return LOCAL_NOTE
        ok = self.analyzer is not None and self.analyzer.available
        return DEV_NOTE if ok else DEV_NO_BURST

    def import_dirs(self) -> list[Path]:
        return default_dirs(self.cfg.data_dir)

    def import_zip(self, path: Path) -> int:
        """비상용 zip 을 검증·적용하고 바로 테마까지 바꾼다. 실패는 ZipImportError."""
        if self.device is None:
            raise RuntimeError("페어링 전에는 가져올 수 없음")
        v = self.store.import_zip(path, self.device)  # 행사가 다른 zip 은 여기서 거절된다
        self._load_bundle(self.store.current())
        log.info("비상용 번들 v%s 적용: %s", v, path)
        return v

    # ── 장면 전환 ────────────────────────────────────────────────────
    def go(self, scene: Scene) -> None:
        if self.scene is not None:
            try:
                self.scene.exit()
            except Exception:
                log.exception("장면 exit 오류")
        self.scene = scene
        self.tracker.cancel()  # 손가락을 댄 채 장면이 넘어가면 뗄 때 탭이 되지 않게
        self._went_at = self.time_fn()
        scene.enter()

    def taps_blocked(self) -> bool:
        """장면이 막 바뀌어 탭을 버려야 하는가."""
        return self.time_fn() - self._went_at < TAP_GUARD_SEC

    def home(self) -> None:
        if self.device is None and self.local and self.bundle is not None:
            self.go(IdleScene(self))
        elif self.device is None:
            self.go(PairingScene(self))
        elif self.bundle is None:
            self.go(WaitingScene(self))
        else:
            self.go(IdleScene(self))

    # ── 촬영 흐름: 필터 → [스티커] → 프레임 → 촬영 (그 뒤는 장면들이 잇는다) ──
    def start_shoot(self) -> None:
        """대기 화면에서 시작. 선택지가 하나뿐인 단계는 건너뛴다."""
        if self.bundle is None or not self.bundle.frames:
            log.warning("쓸 수 있는 프레임이 없어 촬영을 시작하지 않음")
            return
        self._options = shoot_options(self)
        self._chosen = {k: (opts[0][0] if opts else None) for k, opts in self._options.items()}
        self._next_choice(None)

    def chose(self, kind: str, value: object) -> None:
        """ChooseScene 에서 Enter."""
        self._chosen[kind] = value
        self._next_choice(kind)

    def chosen_filter(self) -> str:
        return str(self._chosen.get("F") or "original")

    def _next_choice(self, after: str | None) -> None:
        order = "FKR"
        for kind in order[order.index(after) + 1 if after else 0:]:
            opts = self._options.get(kind) or []
            if len(opts) > 1:
                self.go(ChooseScene(self, kind, opts))
                return
        self._begin_capture()

    def _begin_capture(self) -> None:
        frame = self.bundle.frames[self._chosen["R"]]
        with Image.open(self.store.asset_path(frame["asset"])) as im:
            png = im.convert("RGBA")
        capture = self.bundle.settings["capture"]
        session = ShootSession(frame, capture)
        session.filter = self.chosen_filter()
        sticker = self._chosen.get("K")
        session.sticker = sticker.id if sticker is not None else None
        self.go(CaptureScene(self, Shoot(session, png, sticker, bool(capture["mirror"]))))

    def close_admin(self) -> None:
        self.admin = None

    def _safe(self, fn) -> None:
        """한 장면의 오류로 부스 전체가 멈추지 않게 한다. 처음 화면으로 되돌린다."""
        try:
            fn()
        except Exception:
            log.exception("[app] 장면 오류 — 처음 화면으로 돌아갑니다")
            try:
                self.home()
            except Exception:
                log.exception("처음 화면으로도 갈 수 없음")

    def _admin_safe(self, fn) -> None:
        """관리자 패널 오류는 패널만 닫는다."""
        try:
            fn()
        except Exception:
            log.exception("[app] 관리자 패널 오류 — 패널을 닫습니다")
            self.admin = None

    # ── 메인 루프 ────────────────────────────────────────────────────
    def step(self, dt: float, events: list[pygame.event.Event]) -> None:
        """한 프레임: 입력 → 갱신 → 번들 적용 → 리모컨 → 그리기 (화면 flip 은 run 이 한다)."""
        if self._revoked.is_set():
            self._revoked.clear()
            if self.device is not None:
                self.unpair(REVOKED_MESSAGE)
        self.frame_id, self.frame = self.camera.read()

        for event in events:
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION):
                # 마우스(터치) 이벤트는 인식기로만 간다 — 장면 · 패널의 handle 은 키보드만 본다
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.input_kind = "touch"
                gestures = self.tracker.feed(event)
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1 and self.taps_blocked():
                    self.tracker.cancel()  # 전환 직후에 시작한 누름은 뗀 뒤에도 탭 · 길게 누르기 · 끌기가 되지 않는다
                for g in gestures:
                    self._gesture(g)
            elif event.type == pygame.KEYDOWN and self._key_down(event):
                continue
            elif self.admin is not None:
                self._admin_safe(lambda e=event: self.admin.handle(e))
            else:
                self._safe(lambda e=event: self.scene.handle(e))

        for g in self.tracker.tick():
            self._gesture(g)

        self._safe(lambda: self.scene.update(dt))
        if self.admin is not None:
            self._admin_safe(lambda: self.admin.update(dt))
        self._maybe_swap_bundle()
        self._update_remote()
        self._draw(self.screen)

    def _key_down(self, event: pygame.event.Event) -> bool:
        """키 입력 — 입력 종류를 key 로 하고, 관리자 단축키면 True."""
        self.input_kind = "key"
        return self._global_key(event)

    def _gesture(self, g: Gesture) -> None:
        """인식된 제스처를 패널(열려 있으면) 또는 장면에 나눠 준다."""
        if g.kind == "long":
            # 구석 길게 누르기 = ESC. 페어링 뒤 · 연결 없이 사용 중에만, 패널이 이미 열려 있으면 아무 일 없음
            if (self.device is not None or self.local) and self.admin is None:
                self.admin = AdminPanel(self)
                self.tracker.cancel()
        elif g.kind == "tap":
            if self.taps_blocked():
                return
            if self.admin is not None:
                self._admin_safe(lambda: self.admin.hits.tap(g.pos))
            else:
                self._safe(lambda: self.scene.hits.tap(g.pos))
        elif self.admin is None:  # drag · drag_end — 끌기도 입력이므로 타이머를 되돌린다
            self._safe(lambda: (self.scene.poke(), self.scene.drag(g)))

    def _global_key(self, event: pygame.event.Event) -> bool:
        k = event.key
        if k == pygame.K_ESCAPE:
            self.admin = None if self.admin is not None else AdminPanel(self)
            return True
        if k == pygame.K_F5:
            self.close_admin()
            self._safe(self.home)
            return True
        if k == pygame.K_F2:
            self._safe(self.scene.skip)
            return True
        return False

    def _update_remote(self) -> None:
        if self.theme.title != self._remote_title:
            self._remote_title = self.theme.title
            self.remote.set_title(self.theme.title)
        try:
            line = self.admin.remote_state() if self.admin is not None else self.scene.remote_state()
        except Exception:
            log.exception("리모컨 상태 오류")
            line = "-"
        self.remote.set(line)

    def _draw(self, surf: pygame.Surface) -> None:
        self.scene.hits.clear()  # 그리면서 다시 등록한다
        if self.admin is not None:
            self.admin.hits.clear()
        self._draw_backdrop(surf)
        self._safe(lambda: self.scene.draw(surf))
        self._draw_credit(surf)
        if self.admin is not None:
            self._admin_safe(lambda: self.admin.draw(surf))
        if not self.camera.connected:
            self._draw_camera_lost(surf)

    def _draw_camera_lost(self, surf: pygame.Surface) -> None:
        """위쪽 알림 띠 — 무대 크기와 색 역할(제목색 면 + 그 위에서 읽히는 글자)만 쓴다."""
        st, roles = self.stage, self.theme.roles
        sp = st.tokens["space"]["step"]
        size = st.size("label")
        band = pygame.Rect(0, 0, min(800, st.w - 2 * sp[4]), size + 2 * sp[2])
        band.midtop = (st.w // 2, sp[2])
        ui.panel(surf, band, roles["title"], radius=band.height // 2, alpha=int(255 * st.tokens["color"]["alpha"]["overlay"] + 0.5))
        ui.text(surf, "카메라 연결이 끊겼습니다. 다시 연결 중…", size, ui.ink_on(roles["title"]), band.center, face="label",
                max_width=band.width - 2 * sp[3])

    def _draw_backdrop(self, surf: pygame.Surface) -> None:
        """공용 바탕 — 장면이 자기 배경(self.bg)을 그리면 그 아래로 가려진다."""
        ui.backdrop(surf, self.theme.roles)

    def _draw_credit(self, surf: pygame.Surface) -> None:
        """아래 제작 표기. 장면 배치 토큰에 credit_x · credit_bottom 이 있으면 따른다."""
        if not credit_visible(self.bundle.settings if self.bundle else None):
            return
        layout = {}
        name = getattr(self.scene, "layout_name", None)
        if name:
            layout = self.stage.layout(name)
        x = self.stage.x(layout["credit_x"], "center") if "credit_x" in layout else None
        ui.credit_mark(surf, self.theme.roles, self.theme.tokens, self.stage.size("credit"), x, layout.get("credit_bottom"))

    def run(self, max_frames: int | None = None) -> None:
        """창을 닫거나 패널에서 Q 두 번이면 끝난다. max_frames 는 실행 확인용."""
        frames = 0
        try:
            while self.running:
                dt = min(0.05, self.clock.tick(ui.FPS) / 1000.0)
                self.fps = self.clock.get_fps()
                self.step(dt, pygame.event.get())
                pygame.display.flip()
                frames += 1
                if max_frames is not None and frames >= max_frames:
                    break
        finally:
            self.shutdown()

    def shutdown(self) -> None:
        if self._shut:
            return
        self._shut = True
        # 창부터 닫는다. 스레드는 모두 daemon 이라 요청 도중이어도 오래 기다리지 않는다
        pygame.display.quit()
        self.uploader.stop()
        if self.sync is not None:
            self.sync.stop(timeout=SHUTDOWN_JOIN_SEC)
        self.remote.stop()
        self.camera.release()
        self.detector.close()
        if self.analyzer is not None:
            self.analyzer.close()
        pygame.quit()
