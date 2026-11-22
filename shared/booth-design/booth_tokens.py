"""부스 · 사진 페이지 디자인 토큰 로더 (표준 라이브러리만 — 서버 복사본에서도 그대로 쓴다)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal

TOKENS_PATH = Path(__file__).resolve().parent / "tokens.json"

GROUPS = ("version", "color", "type", "space", "layout", "print", "credit", "motion", "touch")
SCREENS = ("pairing", "dial", "idle", "choose", "capture", "pick", "review", "retake", "share",
           "print_copies", "admin", "import_zip", "waiting", "photo_page")
EVENT_INPUTS = ("primary", "accent", "bg_top", "bg_bottom")
DURATION_NAMES = ("short", "base", "long")
ORIENTATIONS = ("landscape", "portrait")
COMPUTED_ROLES = ("title", "line", "hint", "on_action", "perforation", "action_edge")  # resolve_roles 의 computed 와 같아야 한다
ZERO_OK = {"tilt_deg", "hidden_bottom"}  # 0 이 정상인 값


def load(path: Path | None = None) -> dict:
    """토큰 파일을 읽고 검증해서 돌려준다. 문제가 있으면 ValueError(한국어)."""
    with open(path or TOKENS_PATH, encoding="utf-8") as f:
        tokens = json.load(f)
    validate(tokens)
    return tokens


def _check_positive(value: Any, where: str) -> None:
    """dict · list 안의 숫자를 모두 훑어 0 이하이면 거부한다 (bool · 문자열은 건너뛴다)."""
    if isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if value <= 0:
            raise ValueError(f"{where}: 양수여야 합니다 (지금 {value})")
    elif isinstance(value, dict):
        for k, v in value.items():
            if k not in ZERO_OK:
                _check_positive(v, f"{where}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            _check_positive(v, f"{where}[{i}]")


def validate(tokens: dict) -> None:
    """토큰 구조를 확인한다. 실패하면 ValueError(한국어 메시지)."""
    for g in GROUPS:
        if g not in tokens:
            raise ValueError(f"토큰 묶음 '{g}' 이(가) 없습니다")

    color = tokens["color"]
    for part in ("roles", "fixed", "alpha", "min_contrast"):
        if not isinstance(color.get(part), dict) or not color[part]:
            raise ValueError(f"color.{part} 이(가) 없습니다")
    fixed = color["fixed"]
    allowed = set(EVENT_INPUTS) | set(fixed)
    for role, src in color["roles"].items():
        if not (isinstance(src, str) and (src in allowed or src.startswith("computed:"))):
            raise ValueError(f"색 역할 '{role}' 의 출처 '{src}' 는 행사 색 입력 · 고정색 · computed: 중 하나여야 합니다")
        if src.startswith("computed:") and src[len("computed:"):] not in COMPUTED_ROLES:
            raise ValueError(f"색 역할 '{role}' 의 computed 출처 '{src}' 를 모릅니다 (알려진 값: {' · '.join(COMPUTED_ROLES)})")
    for name, a in color["alpha"].items():
        if isinstance(a, bool) or not isinstance(a, (int, float)) or not 0 < a <= 1:
            raise ValueError(f"color.alpha.{name}: 0 보다 크고 1 이하여야 합니다 (지금 {a})")

    layout = tokens["layout"]
    for s in SCREENS:
        if s not in layout:
            raise ValueError(f"배치에 화면 '{s}' 이(가) 없습니다")
        if not isinstance(layout[s], dict):
            raise ValueError(f"배치 '{s}' 는 가로 · 세로 값을 담은 묶음이어야 합니다")
        for o in ORIENTATIONS:
            if not isinstance(layout[s].get(o), dict) or not layout[s][o]:
                raise ValueError(f"배치 '{s}' 에 '{o}' 값이 없습니다")

    for g in ("type", "space", "layout", "print", "credit", "touch"):
        _check_positive({k: v for k, v in tokens[g].items() if k != "ratio_switch"}, g)
    _check_positive(tokens["motion"].get("degrade", {}), "motion.degrade")
    _check_positive(color.get("min_contrast", {}), "color.min_contrast")

    dur = tokens["motion"].get("duration_ms", {})
    for name in DURATION_NAMES:
        if name not in dur:
            raise ValueError(f"motion.duration_ms 에 '{name}' 이(가) 없습니다")
        _check_positive(dur[name], f"motion.duration_ms.{name}")
    breath = tokens["motion"].get("breath", {})
    _check_positive(breath.get("half_ms", 0), "motion.breath.half_ms")
    if not breath.get("scale", 0) > 1:
        raise ValueError("motion.breath.scale 은 1 보다 커야 합니다")
    for kind, spec in tokens["motion"].get("transition", {}).items():
        if not isinstance(spec, dict) or spec.get("duration") not in DURATION_NAMES:
            raise ValueError(f"motion.transition.{kind}.duration 은 {' · '.join(DURATION_NAMES)} 중 하나여야 합니다")


def layout(tokens: dict, screen: str, orientation: Literal["landscape", "portrait"]) -> dict:
    """화면 하나의 한 방향 배치 값. 없는 화면이면 KeyError."""
    return tokens["layout"][screen][orientation]


# ---- 색 역할 해석 · 대비 검사 -------------------------------------------------
# 대비 식은 WCAG 2 상대 휘도 (0.03928 문턱) — 예전 사진 페이지(server/app/routes/public.py)의 식과 같다.
# 아래 두 상수는 tokens.json 의 color.fixed 와 같아야 한다 (테스트가 대조).
DARK_INK = "#141821"
LIGHT_INK = "#ffffff"


def _luminance(hex_color: str) -> float:
    def ch(i: int) -> float:
        c = int(hex_color[i:i + 2], 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(1) + 0.7152 * ch(3) + 0.0722 * ch(5)


def contrast(a: str, b: str) -> float:
    """WCAG 2 상대 휘도 대비 (1~21)."""
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _min_contrast(fg: str, bgs: list[str]) -> float:
    return min(contrast(fg, b) for b in bgs)


def ink_on(bgs: list[str]) -> str:
    """모든 배경 위에서 최악 대비가 더 큰 글씨 색. 같으면 어두운 쪽."""
    return DARK_INK if _min_contrast(DARK_INK, bgs) >= _min_contrast(LIGHT_INK, bgs) else LIGHT_INK


def mix(fg: str, bg: str, a: float) -> str:
    """fg 를 비율 a 로 bg 와 섞는다. 반올림은 floor(v+0.5) (JS 와 같게; round() 는 쓰지 않는다)."""
    out = "#"
    for i in (1, 3, 5):
        v = int(fg[i:i + 2], 16) * a + int(bg[i:i + 2], 16) * (1 - a)
        out += "%02x" % math.floor(v + 0.5)
    return out


def resolve_roles(tokens: dict, event: dict[str, str]) -> dict[str, str | None]:
    """행사 색 네 개를 색 역할 전부로 풀어낸다. 위·아래 배경을 모두 보고 글씨 색을 정한다."""
    bgs = [event["bg_top"], event["bg_bottom"]]
    primary, accent = event["primary"], event["accent"]
    min_text = tokens["color"]["min_contrast"]["text"]
    min_non_text = tokens["color"]["min_contrast"]["non_text"]

    title = primary if _min_contrast(primary, bgs) >= min_text else ink_on(bgs)
    line = primary if _min_contrast(primary, bgs) >= min_non_text else title
    h = mix(title, event["bg_top"], tokens["color"]["alpha"]["hint"])
    computed = {
        "title": title,
        "line": line,
        "hint": h if _min_contrast(h, bgs) >= min_text else title,
        # 버튼 글자는 큰 글씨(48px 굵게)라 기준이 3.0 — README 참고
        "on_action": ink_on([accent]),
        # 인화지(흰색) 위 필름 구멍 — 연한 대표색이면 구멍이 사라지므로 어두운 글씨색으로
        "perforation": primary if contrast(primary, tokens["color"]["fixed"]["paper"]) >= min_non_text
        else tokens["color"]["fixed"]["dark_ink"],
        "action_edge": None if _min_contrast(accent, bgs) >= min_non_text else line,
    }
    assert set(computed) == set(COMPUTED_ROLES), "COMPUTED_ROLES 와 computed 가 어긋났습니다"
    out: dict[str, str | None] = {}
    for role, src in tokens["color"]["roles"].items():
        if src.startswith("computed:"):
            out[role] = computed[src[len("computed:"):]]
        elif src in event:
            out[role] = event[src]
        else:
            out[role] = tokens["color"]["fixed"][src]
    return out


def credit_visible(event_settings: dict | None) -> bool:
    """제작 표기를 보일지. 지금은 항상 True — 나중에 branding.show_credit 를 읽을 자리."""
    return True
