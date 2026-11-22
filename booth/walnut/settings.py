"""번들 설정 기본값과 보정(clamp). 서버가 새 키를 보내거나 값이 이상해도 죽지 않는다."""

from __future__ import annotations

import copy
import re

# server/app/settings_schema.py 의 default_settings() 와 같아야 한다 (admin 만 pin_hash).
FILTERS = ("original", "mono", "bright", "warm", "cool", "vintage")
ANCHORS = ("forehead", "eyes", "nose", "cheeks", "chin")
MAX_STICKERS = 20

DEFAULTS: dict = {
    "branding": {
        "title": "포토부스", "subtitle": "", "start_text": "버튼을 눌러 시작!",
        "colors": {"primary": "#1b2550", "accent": "#e66e82", "bg_top": "#fff8f9", "bg_bottom": "#eaf4fb"},
        "logo_asset": None, "font_asset": None,
        "privacy_text": "사진은 QR 다운로드를 위해서만 {ttl}시간 보관 후 자동 삭제됩니다.",
    },
    "capture": {"countdown_sec": 10, "between_sec": 2, "extra_shots": 0, "allow_retake": True,
                "review_auto_sec": 25, "mirror": True},
    "filters": {"enabled": list(FILTERS)},
    "stickers": {"enabled": False, "items": []},
    "share": {"qr_enabled": True, "qr_screen_sec": 45, "ttl_hours": 72},
    "print": {"enabled": False, "copies_max": 2},
    "sync": {"interval_sec": 30},
    "admin": {"pin_hash": ""},
}

_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_STICKER_ID = re.compile(r"[a-z0-9_]{1,24}")


def _num(v: object) -> float | None:
    """숫자 또는 숫자 문자열만 받는다. bool 은 숫자가 아니다. NaN·무한대는 거른다."""
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            return None
    if isinstance(v, (int, float)):
        n = float(v)
        return n if n - n == 0 else None
    return None


def _int(v: object, default: int, lo: int, hi: int) -> int:
    n = _num(v)
    return default if n is None else max(lo, min(hi, int(n)))


def _float(v: object, default: float, lo: float, hi: float) -> float:
    n = _num(v)
    return default if n is None else max(lo, min(hi, n))


def _bool(v: object, default: bool) -> bool:
    return v if isinstance(v, bool) else default


def _str(v: object, default: str, lo: int, hi: int) -> str:
    if not isinstance(v, str):
        return default
    v = v.strip()[:hi]
    return v if len(v) >= lo else default


def _dict(v: object) -> dict:
    return v if isinstance(v, dict) else {}


def _sticker(item: object) -> dict | None:
    """잘못된 항목은 None (버린다)."""
    if not isinstance(item, dict):
        return None
    sid, asset, anchor = item.get("id"), item.get("asset"), item.get("anchor")
    if not isinstance(sid, str) or not _STICKER_ID.fullmatch(sid):
        return None
    if not isinstance(asset, str) or not asset or anchor not in ANCHORS:
        return None
    off = item.get("offset")
    if not isinstance(off, (list, tuple)) or len(off) != 2:
        return None
    if _num(item.get("scale")) is None or _num(off[0]) is None or _num(off[1]) is None:
        return None
    return {
        "id": sid, "name": _str(item.get("name"), sid, 1, 20), "asset": asset, "anchor": anchor,
        "scale": _float(item.get("scale"), 1.0, 0.2, 3.0),
        "offset": [_float(off[0], 0.0, -2.0, 2.0), _float(off[1], 0.0, -2.0, 2.0)],
    }


def clamp_settings(raw: object) -> dict:
    """모르는 키는 버리고, 빠진 키는 기본값, 숫자는 범위로 자르고, 타입이 틀리면 기본값."""
    d = copy.deepcopy(DEFAULTS)
    raw = _dict(raw)

    b, rb = d["branding"], _dict(raw.get("branding"))
    b["title"] = _str(rb.get("title"), b["title"], 1, 20)
    b["subtitle"] = _str(rb.get("subtitle"), b["subtitle"], 0, 60)
    b["start_text"] = _str(rb.get("start_text"), b["start_text"], 1, 30)
    rcol = _dict(rb.get("colors"))
    for k in b["colors"]:
        v = rcol.get(k)
        if isinstance(v, str) and _HEX.fullmatch(v):
            b["colors"][k] = v
    for k in ("logo_asset", "font_asset"):
        v = rb.get(k)
        b[k] = v if isinstance(v, str) and v else None
    b["privacy_text"] = _str(rb.get("privacy_text"), b["privacy_text"], 0, 120)

    c, rc = d["capture"], _dict(raw.get("capture"))
    c["countdown_sec"] = _int(rc.get("countdown_sec"), c["countdown_sec"], 3, 30)
    c["between_sec"] = _int(rc.get("between_sec"), c["between_sec"], 0, 10)
    c["extra_shots"] = _int(rc.get("extra_shots"), c["extra_shots"], 0, 6)
    c["allow_retake"] = _bool(rc.get("allow_retake"), c["allow_retake"])
    c["review_auto_sec"] = _int(rc.get("review_auto_sec"), c["review_auto_sec"], 10, 120)
    c["mirror"] = _bool(rc.get("mirror"), c["mirror"])

    en = _dict(raw.get("filters")).get("enabled")
    if isinstance(en, list):
        known = list(dict.fromkeys(x for x in en if isinstance(x, str) and x in FILTERS))
        d["filters"]["enabled"] = known or ["original"]

    st, rs = d["stickers"], _dict(raw.get("stickers"))
    st["enabled"] = _bool(rs.get("enabled"), st["enabled"])
    items = rs.get("items")
    if isinstance(items, list):
        seen: set[str] = set()
        for it in items:
            s = _sticker(it)
            if s and s["id"] not in seen and len(st["items"]) < MAX_STICKERS:
                seen.add(s["id"])
                st["items"].append(s)

    sh, rsh = d["share"], _dict(raw.get("share"))
    sh["qr_enabled"] = _bool(rsh.get("qr_enabled"), sh["qr_enabled"])
    sh["qr_screen_sec"] = _int(rsh.get("qr_screen_sec"), sh["qr_screen_sec"], 10, 300)
    sh["ttl_hours"] = _int(rsh.get("ttl_hours"), sh["ttl_hours"], 1, 720)

    pr, rp = d["print"], _dict(raw.get("print"))
    pr["enabled"] = _bool(rp.get("enabled"), pr["enabled"])
    pr["copies_max"] = _int(rp.get("copies_max"), pr["copies_max"], 1, 5)

    d["sync"]["interval_sec"] = _int(_dict(raw.get("sync")).get("interval_sec"), 30, 10, 600)

    ph = _dict(raw.get("admin")).get("pin_hash")
    d["admin"]["pin_hash"] = ph if isinstance(ph, str) else ""
    return d


# ---- 컷 규칙 (스펙 3.2) ----

def cut_count(slots: list[dict]) -> int:
    """컷 수 = 가장 큰 shot + 1."""
    return max((s["shot"] for s in slots), default=-1) + 1


def cut_ratios(slots: list[dict]) -> list[float]:
    """컷 k 의 비율 = shot==k 인 첫 슬롯(리스트 순서)의 w/h."""
    out: list[float] = []
    for k in range(cut_count(slots)):
        first = next((s for s in slots if s["shot"] == k), None)
        out.append(first["w"] / first["h"] if first else 1.0)
    return out


def preview_ratio(slots: list[dict]) -> float:
    """미리보기 비율: 모든 슬롯의 w/h 를 소수 4자리로 세어 가장 많은 값. 동률이면 먼저 나온 슬롯."""
    counts: dict[float, int] = {}
    for s in slots:
        r = round(s["w"] / s["h"], 4)
        counts[r] = counts.get(r, 0) + 1
    if not counts:
        return 1.0
    return max(counts, key=lambda r: counts[r])  # 동률이면 max 는 먼저 들어온 키를 고른다
