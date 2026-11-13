"""베스트 컷 비교 도구 — 녹화해 둔 시퀀스를 분석기에 다시 돌려 알고리즘의 선택을 보여 준다.

    .\\.venv\\Scripts\\python tools\\compare_best.py [--root booth\\eval_data]

시퀀스마다 이름 · 조건 · 알고리즘이 고른 파일 · 셔터에 가장 가까운 프레임 · reason · 분석 시간을 찍고,
<root>/compare.csv (UTF-8 BOM, 엑셀용)에 프레임별 수치를 쓴다.
<root>/best_labels.csv (열: 시퀀스,베스트,메모 — 베스트는 파일 이름 또는 '없음')가 있으면 사람이 고른 컷과
나란히 보여 주고 일치 수를 센다. 이 도구는 로컬 파일만 읽고 아무것도 업로드하지 않는다.
'없음' 은 알고리즘이 어떤 프레임을 골라도 불일치로 센다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.record_burst import EVAL_ROOT, load_sequence  # noqa: E402
from walnut.analysis import BurstAnalyzer  # noqa: E402

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "face_landmarker.task"
CSV_HEADER = ["시퀀스", "파일", "셔터 대비 초", "선명도", "얼굴 수", "눈 뜸", "방향", "점수", "선택"]
NONE_LABEL = "없음"


def find_sequences(root: Path) -> list[Path]:
    """meta.json 이 있는 하위 폴더를 이름순으로."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(d for d in root.iterdir() if (d / "meta.json").is_file())


def read_labels(root: Path) -> dict[str, str] | None:
    """best_labels.csv 의 {시퀀스: 베스트}. 파일이 없으면 None."""
    path = Path(root) / "best_labels.csv"
    if not path.is_file():
        return None
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {(r.get("시퀀스") or "").strip(): (r.get("베스트") or "").strip() for r in csv.DictReader(f)}


def compare_sequence(analyzer: BurstAnalyzer, seq_dir: Path) -> dict:
    """한 시퀀스를 분석한다. 거울은 쓰지 않는다 (파일 그대로 평가)."""
    frames, shutter_t, meta = load_sequence(seq_dir)
    files = [e["file"] for e in meta["frames"]]
    info = analyzer.submit(frames, shutter_t, False).result().info
    offsets = [c["t"] - shutter_t for c in info["candidates"]]
    nearest = min(range(len(files)), key=lambda i: abs(offsets[i]))
    rows = []
    for i, (name, c) in enumerate(zip(files, info["candidates"])):
        rows.append([seq_dir.name, name, f"{offsets[i]:.3f}", f"{c['sharpness']:.1f}", c["faces"],
                     _fmt(c["eye"]), _fmt(c["frontality"]), _fmt(info["scores"][i]), 1 if i == info["index"] else 0])
    return {
        "name": seq_dir.name, "conditions": list(meta.get("conditions", [])),
        "chosen": files[info["index"]], "nearest": files[nearest],
        "reason": info["reason"], "fallback_used": info["fallback_used"],
        "ms": info["timings"]["total"], "rows": rows,
    }


def _fmt(v) -> str:
    return "" if v is None else f"{v:.3f}"


def write_csv(path: Path, results: list[dict]) -> None:
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for r in results:
            w.writerows(r["rows"])


def summarize(results: list[dict], labels: dict[str, str]) -> dict:
    """라벨이 붙은 시퀀스만 센다. different 는 알고리즘이 사람과 다른 프레임을 고른 횟수."""
    labeled = [r for r in results if r["name"] in labels]
    same = sum(1 for r in labeled if labels[r["name"]] == r["chosen"])
    return {"compared": len(labeled), "same": same, "different": len(labeled) - same}


def format_line(r: dict, labels: dict[str, str] | None) -> str:
    cond = " ".join(r["conditions"]) or "-"
    line = (f"{r['name']}  [{cond}]  알고리즘 {r['chosen']}  셔터 근처 {r['nearest']}  "
            f"reason={r['reason']}  fallback={r['fallback_used']}  {r['ms']:.0f}ms")
    if labels is not None and r["name"] in labels:
        line += f"  사람 {labels[r['name']] or '-'}"
    return line


def run(root: Path, analyzer: BurstAnalyzer, out=print) -> list[dict]:
    root = Path(root)
    labels = read_labels(root)
    results = []
    for d in find_sequences(root):
        try:
            r = compare_sequence(analyzer, d)
        except Exception as exc:  # 시퀀스 하나가 깨져도 나머지는 계속한다
            out(f"{d.name}  건너뜀: {exc}")
            continue
        results.append(r)
        out(format_line(r, labels))
    if not results:
        out(f"비교할 시퀀스가 없습니다: {root}")
        return results
    write_csv(root / "compare.csv", results)
    out(f"프레임별 수치를 썼습니다: {root / 'compare.csv'}")
    if labels is not None:
        s = summarize(results, labels)
        out(f"사람 라벨과 비교: 시퀀스 {s['compared']}개, 일치 {s['same']}개, "
            f"알고리즘이 사람과 다른 컷을 고른 횟수 {s['different']}")
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="베스트 컷 비교 도구 (로컬 파일만 읽고 아무것도 업로드하지 않는다)")
    ap.add_argument("--root", type=Path, default=EVAL_ROOT, help="시퀀스 폴더들이 있는 곳 (기본 booth/eval_data)")
    args = ap.parse_args(argv)
    analyzer = BurstAnalyzer(MODEL_PATH)
    if not analyzer.available:
        print(f"얼굴 모델이 없습니다: {MODEL_PATH} (tools/download_models.py)")
        return 1
    try:
        run(args.root, analyzer)
    finally:
        analyzer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
