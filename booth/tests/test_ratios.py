"""화면비 6종 검사 — 13 장면이 어느 화면비에서도 화면 안에서 그려지고 누를 곳이 화면 밖으로 나가지 않는다.

부스 디자인 체계 3단계 마지막 점검: 옛 고정 상수 제거 · 긴 이름 · 극단적인 행사 색.
화면을 만드는 도구는 test_design_baseline.py 의 walk_screens 를 그대로 쓴다 (장면 하나를 만드는 순서가 두 곳에 있지 않게).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pygame
import pytest

from tests.test_design_baseline import RATIO_WIN, baseline_env, ratio_name, step, walk_screens  # noqa: F401
from walnut import ui
from walnut.booth_design import load
from walnut.theme import Theme

ROOT = Path(__file__).resolve().parents[2]
SCENES = ROOT / "booth" / "walnut" / "scenes"
sys.path.insert(0, str(ROOT / "shared" / "booth-design" / "tests"))
from cases import HARD_CASES, random_cases  # noqa: E402

RATIOS = list(RATIO_WIN)
# walk_screens 가 내주는 장면 이름 → 13 장면 (고르기는 필터 · 프레임 두 번, 숫자 다이얼은 관리자 PIN)
ALL_13 = {
    "03-idle": "idle", "13-waiting": "waiting", "04-choose-filter": "choose", "05-choose-frame": "choose",
    "06-capture": "capture", "07-pick": "pick", "09-retake": "retake", "08-review": "review", "10-share": "share",
    "11-print-copies": "print_copies", "01-pairing": "pairing", "02-dial": "dial", "12-admin": "admin",
    "12b-import": "import_zip",
}


def _hit_rects(app) -> list[pygame.Rect]:
    maps = [app.scene.hits] + ([app.admin.hits] if app.admin is not None else [])
    return [r for m in maps for r, _ in m._items]


# ---- 옛 상수 ----
def test_scenes_have_no_fixed_size_or_direct_color():
    pat = re.compile(r"ui\.(W|H|GREY|GOLD|RED|GREEN)\b")
    for f in [*SCENES.glob("*.py"), SCENES.parent / "app.py"]:
        assert not pat.search(f.read_text(encoding="utf-8")), f


def test_ui_has_no_fixed_size_or_default_palette():
    for n in ("W", "H", "GREY", "GOLD", "RED", "GREEN"):
        assert not hasattr(ui, n), n
    assert not hasattr(ui, "_hex") and ui.hex_rgb("#0a141e") == (10, 20, 30)
    assert not (SCENES / "base.py").read_text(encoding="utf-8").count("def button(")
    assert "def _hex" not in (SCENES / "capture.py").read_text(encoding="utf-8")


# ---- 화면비 6종 ----
@pytest.mark.parametrize("ratio_name", RATIOS)
def test_scenes_draw_and_buttons_stay_on_screen(baseline_env, monkeypatch, ratio_name):
    seen, bad = set(), []
    for stem, app in walk_screens(baseline_env, monkeypatch):
        step(app)  # 그리기
        stage = app.stage.rect()
        assert app.screen.get_size() == stage.size and stage.size == (app.stage.w, app.stage.h)
        rects = _hit_rects(app)
        assert rects or ALL_13[stem] in ("waiting", "capture"), f"{stem}: 누를 곳이 하나도 없다"  # 이 둘은 탭에 반응하지 않는다
        bad += [f"{ratio_name} {stem}: {r} 가 화면 {stage.size} 밖" for r in rects if not stage.contains(r)]
        seen.add(ALL_13[stem])
    assert not bad, "\n".join(bad)
    assert seen == set(ALL_13.values()) and len(seen) == 13


# ---- 긴 이름 ----
MIN_LEGIBLE = 22  # 1080 기준 px — 세로 body(40 x 0.75=30)·caption(22) 아래로 줄면 멀리서 못 읽는다
LONG = "호두네사진관 아주 긴 행사 이름 가나다라마바사아자차카타파하 열두글자 더 붙입니다"[:40]


class TextLog:
    """ui.text 가 그린 글자를 (글자, 그린 면, 자리) 로 남긴다 — 글자 자리는 그 면 기준이다."""

    def __init__(self, monkeypatch):
        self.items: list[tuple[str, pygame.Surface, pygame.Rect]] = []
        self.small: list[str] = []
        real = ui.text

        def spy(surf, s, size, color, pos, *a, **kw):
            r = real(surf, s, size, color, pos, *a, **kw)
            if s:
                clip = r.clip(surf.get_clip())  # 잘려 나가는 부분(목록 밖)은 보이지 않으니 보이는 만큼만 본다
                if clip.width > 0 and clip.height > 0:
                    self.items.append((s, surf, clip))
                    if len(s) > 2 and size >= MIN_LEGIBLE:  # 쓰려던 크기가 읽을 만한 글자만 (작은 표기 · 번호 제외)
                        eff = ui.fit_size(s, size, kw["max_width"], kw.get("face", "body")) if kw.get("max_width") else size
                        if eff < MIN_LEGIBLE:
                            self.small.append(f"{s!r} 가 {eff}px 로 줄었다")
            return r
        monkeypatch.setattr(ui, "text", spy)

    def clear(self) -> None:
        self.items.clear()
        self.small.clear()

    def overflows(self, app) -> list[str]:
        """글자가 그려진 면(버튼 몸통이면 버튼) 밖, 또는 그 자리를 덮는 가장 작은 누르는 영역 밖으로 나간 것."""
        rects = _hit_rects(app)
        out = []
        for s, surf, r in self.items:
            if len(s) <= 2:  # 번호 동그라미 — 동그라미가 자리를 정한다
                continue
            if surf is not app.screen:
                if r.left < 0 or r.right > surf.get_width():
                    out.append(f"{s!r} {r} 가 면 {surf.get_size()} 밖")
                continue
            if r.left < 0 or r.right > app.stage.w:
                out.append(f"{s!r} {r} 가 화면 밖")
            inside = [h for h in rects if h.collidepoint(r.center) and h.width < app.stage.w]
            if inside:
                h = min(inside, key=lambda q: q.w * q.h)
                slack = app.stage.tokens["space"]["step"][1]  # 목록 끝 칸은 포커스 고리만큼 더 넓게 잘린다
                if r.left < h.left - slack or r.right > h.right + slack:
                    out.append(f"{s!r} {r} 가 버튼 {h} 밖")
        return out


@pytest.mark.parametrize("ratio_name", RATIOS)
def test_long_names_stay_inside_their_buttons(baseline_env, monkeypatch, ratio_name):
    from tests.test_touch_scenes import make_shoot
    from walnut.scenes.choose import ChooseScene
    from walnut.scenes.pick import PickScene
    from walnut.scenes.retake import RetakeScene
    from walnut.scenes import import_zip as import_mod
    from PIL import Image

    log = TextLog(monkeypatch)
    app = baseline_env.paired({"branding": {"title": LONG, "subtitle": LONG, "start_text": LONG}}, two_frames=True)
    problems: list[str] = []

    def check(label: str) -> None:
        step(app)
        problems.extend(f"{ratio_name} {label}: {p}" for p in log.overflows(app) + log.small)
        log.clear()

    check("idle")  # 40자 제목 · 부제 · 시작 버튼 글자
    longs18 = [(i, f"{i:02d} {LONG}") for i in range(18)]
    for kind in ("F", "R"):
        values = [(v if kind == "F" else 0, label) for v, label in longs18]
        app.go(ChooseScene(app, kind, values))
        check(f"choose {kind} 18개")
        app.scene.sel = 17
        check(f"choose {kind} 마지막 항목")
    shoot = make_shoot(app, 4, 18, extra=14)
    app.go(PickScene(app, shoot))
    check("pick 18장")
    app.go(RetakeScene(app, make_shoot(app, 18, 18), Image.new("RGB", (100, 100))))
    check("retake 18컷")
    monkeypatch.setattr(import_mod, "find_zips", lambda dirs: [Path(f"/x/{i:02d}_{LONG}.zip") for i in range(18)])
    app.go(import_mod.ImportZipScene(app))
    check("import 18개")
    assert not problems, "\n".join(problems)


# ---- 극단적인 행사 색 ----
def _theme(case: dict) -> Theme:
    colors = {k: case[k] for k in ("primary", "accent", "bg_top", "bg_bottom")}
    bundle = SimpleNamespace(settings={"branding": {"colors": colors}})
    return Theme.from_bundle(bundle, lambda sha: None)


def _lum(rgb) -> float:
    def ch(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(rgb[0]) + 0.7152 * ch(rgb[1]) + 0.0722 * ch(rgb[2])


def _contrast(a, b) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


EXTREME_CASES = HARD_CASES + random_cases(seed=20261104, n=24)


@pytest.mark.parametrize("case", EXTREME_CASES, ids=lambda c: c["name"])
def test_extreme_event_colors_keep_contrast(case):
    th = _theme(case)
    roles = th.roles
    need = th.tokens["color"]["min_contrast"]
    bgs = [roles["background_top"], roles["background_bottom"]]
    # 위아래 배경이 너무 달라 어느 글씨색도 기준을 못 넘는 행사면 가능한 최선이어야 한다
    best = max(min(_contrast(i, b) for b in bgs) for i in (ui.hex_rgb(th.tokens["color"]["fixed"]["dark_ink"]),
                                                              ui.hex_rgb(th.tokens["color"]["fixed"]["light_ink"])))
    for role in ("title", "hint"):
        got = min(_contrast(roles[role], b) for b in bgs)
        assert got >= need["text"] or got >= best - 0.01, (role, got)
    assert _contrast(roles["on_action"], roles["action"]) >= 3.0  # 버튼 글자는 큰 글씨 (토큰 README)
    assert min(_contrast(roles["line"], b) for b in bgs) >= need["non_text"] or best < need["non_text"]


# ---- 인쇄 매수: 꺼진 화살표 ----
def test_print_copies_disabled_arrow_does_not_allocate_a_screen_sized_layer(baseline_env, monkeypatch, ratio_name):
    made: list[tuple[int, int]] = []
    real = pygame.Surface

    class Spy(real):
        def __init__(self, size, *a, **kw):
            made.append(tuple(size))
            super().__init__(size, *a, **kw)

    app = None
    for stem, app in walk_screens(baseline_env, monkeypatch):
        if stem == "11-print-copies":
            break
    assert app.scene.copies == 1  # 1장이면 '줄이기' 화살표가 꺼진 상태
    monkeypatch.setattr(pygame, "Surface", Spy)
    step(app)
    screen = app.screen.get_size()
    assert screen not in made, "꺼진 화살표가 화면 크기 면을 만들었다"


def test_action_button_wraps_a_long_label_into_two_lines_instead_of_shrinking(monkeypatch):
    pygame.init()
    ui.clear_caches()  # 앞선 시험이 pygame 을 닫으면 글꼴 캐시가 죽어 있다
    surf = pygame.Surface((800, 200), pygame.SRCALPHA)
    roles = Theme.from_bundle(None, lambda sha: None).roles
    log = TextLog(monkeypatch)
    ui.action_button(surf, (20, 40, 760, 105), "짧은 이름", roles)
    assert len(log.items) == 1
    log.clear()
    ui.action_button(surf, (20, 40, 760, 105), LONG, roles)
    assert len(log.items) == 2 and "".join(s for s, _, _ in log.items).replace(" ", "") == LONG.replace(" ", "")  # 두 줄로 다 들어간다


# ---- 겹침 ----
@pytest.mark.parametrize("ratio_name", RATIOS)
@pytest.mark.parametrize("input_kind", ["key", "touch"])
def test_choose_hint_clears_preview_and_list(baseline_env, monkeypatch, ratio_name, input_kind):
    """안내 문구가 카메라 미리보기(테두리까지) · 목록 항목과 겹치지 않는다. 문구는 입력 방식마다 길이가 다르다."""
    from walnut.scenes import choose as choose_mod

    for stem, app in walk_screens(baseline_env, monkeypatch):
        if stem == "04-choose-filter":
            break
    app.input_kind = input_kind
    previews, hints = [], []
    real_live, real_text = choose_mod.draw_live, ui.text

    def spy_live(surf, live, center, size, ink):
        r = real_live(surf, live, center, size, ink)
        previews.append(r.inflate(16, 16))  # draw_live 가 그리는 테두리까지
        return r

    def spy_text(surf, s, *a, **k):
        r = real_text(surf, s, *a, **k)
        if s == app.scene._hint():
            hints.append(r)
        return r

    monkeypatch.setattr(choose_mod, "draw_live", spy_live)
    monkeypatch.setattr(ui, "text", spy_text)
    step(app)
    assert previews and hints
    assert not hints[-1].colliderect(previews[-1]), f"문구 {hints[-1]} · 미리보기 {previews[-1]}"
    bad = [r for r in _hit_rects(app) if hints[-1].colliderect(r)]
    assert not bad, f"문구 {hints[-1]} · 목록 {bad}"
