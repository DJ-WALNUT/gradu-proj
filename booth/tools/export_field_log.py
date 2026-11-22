"""현장 기록 내보내기 — 지인 시험 · 행사 뒤 기록을 zip 하나로 묶는다.

    .\\.venv\\Scripts\\python tools\\export_field_log.py --since 2026-11-20 --out field.zip
    .\\.venv\\Scripts\\python tools\\export_field_log.py --since 2026-11-20 --with-samples --with-collage --out field.zip

기본으로 들어가는 것 (사진 없음):
  logs/capture_metrics.jsonl   --since 날짜부터의 촬영 기록 줄 (날짜가 없는 이전 형식 줄은 빠진다)
  logs/booth-YYYY-MM-DD*.log   --since 날짜부터의 진단 로그 (QR 토큰 · 합성본 파일 이름은 가린다)
  export.json                  무엇을 넣었는지
--with-collage: 합성본을 collage/<shoot_id>.jpg 로 이름을 바꿔 넣는다 (파일 이름의 QR 토큰은 빠진다).
--with-samples: eval_data/field_<날짜>_<테스트 이름>/ 샘플 시퀀스를 samples/ 아래에 넣는다 (동의한 지인 시험만).

이 도구는 아무것도 업로드하지 않는다. 만든 zip 은 직접 첨부하고, 보낸 뒤에는 지운다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from walnut.fieldlog import parse_lines  # noqa: E402

BOOTH = Path(__file__).resolve().parent.parent
REDACTED = "<토큰>"
_LOG_NAME = re.compile(r"^booth-(\d{4}-\d{2}-\d{2})(?:\.\d+)?\.log$")
_FIELD_DIR = re.compile(r"^field_(\d{8})_")
# 합성본 파일 이름(<행사>_<월일-시분초>_<토큰>) · 사진 주소(/p/<토큰>) — 알려진 토큰을 못 찾았을 때를 위한 안전망
_NAME_RE = re.compile(r"\d+_\d{4}-\d{6}_[A-Za-z0-9_-]{16}")
_URL_RE = re.compile(r"/p/[A-Za-z0-9_-]{16}")


def known_tokens(data_dir: Path) -> set[str]:
    """data/collage 파일 이름과 outbox(하위 폴더 포함)의 토큰."""
    out: set[str] = set()
    for p in (Path(data_dir) / "collage").glob("*.jpg"):
        parts = p.stem.split("_", 2)
        if len(parts) == 3 and parts[2]:
            out.add(parts[2])
    for p in (Path(data_dir) / "outbox").rglob("*.jpg"):
        out.add(p.stem.lstrip("."))
    return {t for t in out if len(t) >= 8}


def redact(text: str, tokens: set[str]) -> str:
    text = _NAME_RE.sub(REDACTED, text)
    text = _URL_RE.sub("/p/" + REDACTED, text)
    for t in sorted(tokens, key=len, reverse=True):
        text = text.replace(t, REDACTED)
    return text


def _line_date(rec: dict) -> str:
    at = rec.get("at")
    return at[:10] if isinstance(at, str) else ""


def export(data_dir: Path, eval_dir: Path, since: date, out: Path, *,
           with_samples: bool = False, with_collage: bool = False) -> dict:
    data_dir, eval_dir, out = Path(data_dir), Path(eval_dir), Path(out)
    day = since.isoformat()
    tokens = known_tokens(data_dir)
    summary = {"since": day, "made_at": datetime.now().isoformat(timespec="seconds"),
               "lines": 0, "undated_skipped": 0, "broken_skipped": 0, "logs": [], "collages": 0, "samples": 0}
    out.parent.mkdir(parents=True, exist_ok=True)
    metrics = data_dir / "logs" / "capture_metrics.jsonl"
    recs: list[dict] = []
    if metrics.is_file():
        recs, summary["broken_skipped"] = parse_lines(metrics.read_text(encoding="utf-8", errors="replace").splitlines())
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        kept = []
        for r in recs:
            d = _line_date(r)
            if not d:
                summary["undated_skipped"] += 1
            elif d >= day:
                kept.append(json.dumps(r, ensure_ascii=False))
        summary["lines"] = len(kept)
        z.writestr("logs/capture_metrics.jsonl", redact("".join(x + "\n" for x in kept), tokens))

        for p in sorted((data_dir / "logs").glob("booth-*.log")):
            m = _LOG_NAME.match(p.name)
            if m and m.group(1) >= day:
                z.writestr(f"logs/{p.name}", redact(p.read_text(encoding="utf-8", errors="replace"), tokens))
                summary["logs"].append(p.name)

        if with_collage:
            by_hash = {r["collage_sha256"]: r.get("shoot_id") for r in recs
                       if r.get("type") == "result" and r.get("collage_sha256")}
            unknown = 0
            for p in sorted((data_dir / "collage").glob("*.jpg")):
                if date.fromtimestamp(p.stat().st_mtime) < since:
                    continue
                blob = p.read_bytes()
                sid = by_hash.get(hashlib.sha256(blob).hexdigest())
                if sid:
                    name = f"collage/{sid}.jpg"
                else:  # 촬영 기록이 꺼져 있던 때의 합성본 — 촬영 id 를 모른다
                    unknown += 1
                    name = f"collage/unknown_{unknown:03d}.jpg"
                z.writestr(name, blob)
                summary["collages"] += 1

        if with_samples and eval_dir.is_dir():
            for d in sorted(eval_dir.iterdir()):
                m = _FIELD_DIR.match(d.name)
                if not (d.is_dir() and m and m.group(1) >= since.strftime("%Y%m%d")):
                    continue
                for p in sorted(d.rglob("*")):
                    if p.is_file():
                        z.write(p, f"samples/{p.relative_to(eval_dir).as_posix()}")
                summary["samples"] += sum(1 for _ in d.glob("*/meta.json"))

        z.writestr("export.json", json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="호두네사진관 현장 기록 내보내기 (업로드하지 않음)")
    ap.add_argument("--since", required=True, help="이 날짜부터 (YYYY-MM-DD)")
    ap.add_argument("--out", required=True, help="만들 zip 경로")
    ap.add_argument("--with-samples", action="store_true", help="샘플 시퀀스(원본 얼굴 사진)도 넣는다")
    ap.add_argument("--with-collage", action="store_true", help="합성본도 넣는다 (이름은 shoot_id)")
    ap.add_argument("--data", default=str(BOOTH / "data"), help="부스 data 폴더 (개발자 모드는 data-dev)")
    ap.add_argument("--eval", default=str(BOOTH / "eval_data"), help="샘플 폴더")
    args = ap.parse_args(argv)
    try:
        since = date.fromisoformat(args.since)
    except ValueError:
        print(f"날짜 형식이 아닙니다: {args.since} (예: 2026-11-20)")
        return 2
    s = export(Path(args.data), Path(args.eval), since, Path(args.out),
               with_samples=args.with_samples, with_collage=args.with_collage)
    print(f"만듦: {args.out}")
    print(f"  촬영 기록 {s['lines']}줄 · 진단 로그 {len(s['logs'])}개 · 합성본 {s['collages']}장 · 샘플 {s['samples']}개")
    if s["undated_skipped"]:
        print(f"  날짜가 없는 이전 형식 줄 {s['undated_skipped']}개는 넣지 않았습니다")
    print("이 도구는 업로드하지 않습니다. zip 을 직접 첨부하고, 보낸 뒤에는 지워 주세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
