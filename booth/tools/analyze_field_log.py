"""현장 기록 분석 — 내보낸 zip(또는 폴더 · jsonl)의 촬영 기록을 표로 요약한다.

    .\\.venv\\Scripts\\python tools\\analyze_field_log.py field.zip
    .\\.venv\\Scripts\\python tools\\analyze_field_log.py data\\logs

촬영 수, 컷 reason 분포, 폴백률, 단계별 평균 · 95백분위 지연, 크롭 reason, F9 로 표시한 촬영 목록,
'찍은 그대로' · 'AI 추천' 고르기의 AI 채택률 (cut 줄 choice — 더 찍고 고르기는 최종으로 고르지 않은 사진까지 사진 단위로 센다),
사람 찾기로 구도를 잡은 컷 수 (얼굴 0 → 사람) · 얼굴에 사람 찾기 머리를 더한 컷 수 (cut 줄 person_heads).
잘린 줄(전원 차단)은 건너뛰고 그 수를 알린다. 예전 'baseline' 줄(shoot_id 없음)은 합성 지연으로만 센다.
이 도구는 로컬 파일만 읽고 아무것도 업로드하지 않는다.
"""

from __future__ import annotations

import argparse
import math
import sys
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from walnut.fieldlog import parse_lines  # noqa: E402

CUT_STAGES = ("collect_ms", "analyze_ms", "total_ms")
STAGE_NAMES = {"collect_ms": "후보 수집", "analyze_ms": "분석", "total_ms": "컷 전체", "compose_ms": "합성"}
SHOOT_TYPES = ("session", "cut", "crop", "result")
CHOICES = ("ai", "as_shot", "timeout_ai", "skipped")  # cut 줄 choice 값


def load_records(path: Path) -> tuple[list[dict], int]:
    """zip · 폴더 · jsonl 파일에서 촬영 기록을 읽는다 → (기록, 건너뛴 줄 수)."""
    path = Path(path)
    texts: list[str] = []
    if path.is_file() and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.endswith(".jsonl")]
            texts = [z.read(n).decode("utf-8", "replace") for n in sorted(names)]
    elif path.is_file():
        texts = [path.read_text(encoding="utf-8", errors="replace")]
    elif path.is_dir():
        files = sorted(path.rglob("capture_metrics*.jsonl")) or sorted(path.rglob("*.jsonl"))
        texts = [p.read_text(encoding="utf-8", errors="replace") for p in files]
    recs, broken = [], 0
    for t in texts:
        r, b = parse_lines(t.splitlines())
        recs += r
        broken += b
    return recs, broken


def _num(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def stats(values: list[float]) -> dict:
    """n · 평균 · 95백분위(가까운 순위) · 최대."""
    v = sorted(values)
    if not v:
        return {"n": 0, "mean": None, "p95": None, "max": None}
    return {"n": len(v), "mean": sum(v) / len(v), "p95": v[max(0, math.ceil(0.95 * len(v)) - 1)], "max": v[-1]}


def choice_summary(cuts: list[dict]) -> dict:
    """고르기 결과. 고르기가 있었던 컷(asked) = ai · as_shot · timeout_ai, 손님이 직접 고른 컷(picked) = ai · as_shot.

    ai_rate = (ai + timeout_ai) / asked, picked_ai_rate = ai / picked, picked_ms = 직접 고른 컷의 고르는 데 걸린 시간."""
    counts = Counter(str(c["choice"]) for c in cuts if "choice" in c)
    asked = counts["ai"] + counts["as_shot"] + counts["timeout_ai"]
    picked = counts["ai"] + counts["as_shot"]
    ms = [x for x in (_num(c.get("choice_ms")) for c in cuts if c.get("choice") in ("ai", "as_shot")) if x is not None]
    return {"counts": dict(counts), "asked": asked, "picked": picked,
            "ai_rate": (counts["ai"] + counts["timeout_ai"]) / asked if asked else None,
            "picked_ai_rate": counts["ai"] / picked if picked else None,
            "picked_ms": stats(ms)}


def person_summary(cuts: list[dict]) -> dict:
    """사람 찾기 (cut 줄 person_heads · person_ms). ran = 사람 찾기가 돈 컷 (person_ms 가 있음),
    only = 구도용 얼굴이 모두 사람 찾기 머리인 컷 (얼굴 0 → 사람), added = 얼굴에 사람 찾기 머리를 더한 컷."""
    ran = [c for c in cuts if _num(c.get("person_ms")) is not None]
    only = added = 0
    for c in cuts:
        heads = _num(c.get("person_heads")) or 0
        if heads <= 0:
            continue
        if len(c.get("faces") or []) <= heads:
            only += 1
        else:
            added += 1
    return {"ran": len(ran), "only": only, "added": added, "ms": stats([_num(c["person_ms"]) for c in ran])}


def summarize(recs: list[dict]) -> dict:
    cuts = [r for r in recs if r.get("type") == "cut"]
    results = [r for r in recs if r.get("type") == "result"]
    legacy = [r for r in recs if r.get("type") == "baseline"]  # 예전 형식 — 합성 지연으로 바꿔 센다
    crops = [r for r in recs if r.get("type") == "crop"]
    shoots = {r.get("shoot_id") for r in recs if r.get("type") in SHOOT_TYPES and r.get("shoot_id")}
    latency = {k: stats([x for x in (_num(c.get(k)) for c in cuts) if x is not None]) for k in CUT_STAGES}
    latency["compose_ms"] = stats([x for x in (_num(r.get("compose_ms")) for r in results + legacy) if x is not None])
    fb = sum(1 for c in cuts if c.get("fallback_used"))
    crop_fb = sum(1 for c in crops if c.get("fallback_used"))
    retakes = [x for x in (_num(r.get("retakes")) for r in results) if x is not None]
    return {
        "shoots": len(shoots), "cuts": len(cuts),
        "reasons": dict(Counter(str(c.get("reason")) for c in cuts)),
        "fallback_rate": fb / len(cuts) if cuts else None,
        "latency": latency,
        "crops": len(crops), "crop_reasons": dict(Counter(str(c.get("reason")) for c in crops)),
        "crop_fallback_rate": crop_fb / len(crops) if crops else None,
        "retakes": {"shoots": len(retakes), "with_retake": sum(1 for x in retakes if x > 0)},
        "samples": dict(Counter(str(c["sample"]) for c in cuts if "sample" in c)),
        "choice": choice_summary(cuts),
        "person": person_summary(cuts),
        "legacy_baseline": len(legacy),
        "marks": [{"shoot_id": m.get("shoot_id"), "at": m.get("at"), "scene": m.get("scene", ""),
                   "memo": m.get("memo", "")} for m in recs if m.get("type") == "mark"],
    }


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{v * 100:.1f}%"


def _ms(v: float | None) -> str:
    return "-" if v is None else f"{v:.1f}"


def _dist(d: dict) -> list[str]:
    total = sum(d.values()) or 1
    return [f"  {k:<16} {n:>5}  {n / total * 100:5.1f}%" for k, n in sorted(d.items(), key=lambda kv: -kv[1])]


def format_report(s: dict) -> str:
    out = [f"촬영 수            {s['shoots']}",
           f"컷 수              {s['cuts']}",
           f"폴백률             {_pct(s['fallback_rate'])}"]
    if s.get("broken"):
        out.append(f"건너뛴 줄 {s['broken']} (잘렸거나 읽을 수 없는 줄)")
    if s.get("legacy_baseline"):
        out.append(f"이전 형식(baseline) 줄 {s['legacy_baseline']}개 — 합성 지연에만 넣었습니다")
    out += ["", "컷 reason 분포"] + (_dist(s["reasons"]) or ["  (없음)"])
    out += ["", f"  {'단계':<10} {'n':>5} {'평균 ms':>9} {'95% ms':>9} {'최대 ms':>9}"]
    for k in (*CUT_STAGES, "compose_ms"):
        st = s["latency"][k]
        out.append(f"  {STAGE_NAMES[k]:<10} {st['n']:>5} {_ms(st['mean']):>9} {_ms(st['p95']):>9} {_ms(st['max']):>9}")
    if s.get("crops"):
        out += ["", f"크롭 {s['crops']}개 · 가운데 크롭으로 돌아간 비율 {_pct(s['crop_fallback_rate'])}"]
        out += _dist(s["crop_reasons"])
    rt = s.get("retakes") or {}
    if rt.get("shoots"):
        out += ["", f"완료한 촬영 {rt['shoots']}건 중 다시 찍기 {rt['with_retake']}건"]
    ch = s.get("choice") or {}
    if ch.get("asked"):
        c = ch["counts"]
        out += ["", f"AI 채택률 (고르기 {ch['asked']}컷 중 AI 추천)  {_pct(ch['ai_rate'])}",
                f"  손님이 직접 고른 {ch['picked']}컷 중 AI 추천  {_pct(ch['picked_ai_rate'])}"
                f"  (고르는 시간 평균 {_ms(ch['picked_ms']['mean'])} ms)",
                "  " + " · ".join(f"{k} {c.get(k, 0)}" for k in CHOICES)]
    ps = s.get("person") or {}
    if ps.get("ran") or ps.get("only") or ps.get("added"):
        out += ["", f"사람 찾기가 돈 컷 {ps['ran']}  (평균 {_ms(ps['ms']['mean'])} ms · 95% {_ms(ps['ms']['p95'])} ms)",
                f"  사람 찾기로 구도를 잡은 컷 (얼굴 0 → 사람)  {ps['only']}",
                f"  얼굴에 사람 찾기 머리를 더한 컷  {ps['added']}"]
    if s.get("samples"):
        out += ["", "샘플 저장 " + ", ".join(f"{k} {n}" for k, n in sorted(s["samples"].items()))]
    out += ["", f"표시한 촬영 (F9) {len(s['marks'])}건"]
    for m in s["marks"]:
        out.append(f"  {m['at'] or '-'}  {m['shoot_id'] or '-'}  {m['scene']}  {m['memo']}".rstrip())
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="호두네사진관 현장 기록 분석")
    ap.add_argument("path", help="export_field_log.py 가 만든 zip, 또는 폴더 · jsonl 파일")
    args = ap.parse_args(argv)
    p = Path(args.path)
    if not p.exists():
        print(f"찾을 수 없습니다: {p}")
        return 2
    recs, broken = load_records(p)
    print(format_report({**summarize(recs), "broken": broken}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
