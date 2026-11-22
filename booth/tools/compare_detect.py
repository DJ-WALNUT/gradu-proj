"""검출 비교 도구 — 녹화해 둔 시퀀스를 검출 전략 셋(전체 · 좌우 반쪽 · 둘 다)으로 다시 돌려 비교한다.

    .\\.venv\\Scripts\\python tools\\compare_detect.py [--root booth\\eval_data] [--debug-dir <폴더>]

시퀀스마다 · 전체로 전략별 '얼굴을 하나 이상 찾은 프레임 비율' · '프레임당 평균 얼굴 수' ·
'프레임당 분석 ms (평균 · 최대)' 를 찍고 <root>/compare_detect.csv (UTF-8 BOM, 엑셀용)에 쓴다.
ms 는 회색 변환 · 검출 · 선명도까지 프레임 하나에 든 시간이다 (처음 모델 불러오기는 빼고 잰다).
현장 샘플 폴더(eval_data/field_<날짜>_<이름>/)는 --root 로 그 폴더를 주면 그대로 읽힌다.

--debug-dir 를 주면 프레임마다 전략별 얼굴 박스를 그린 JPEG 를 그 폴더에 쓴다.
원본 얼굴 사진이 그대로 담기므로 기본은 끔이다 — 확인한 뒤 지우고, 저장소에 넣거나 밖으로 보내지 않는다.
이 도구는 로컬 파일만 읽고 아무것도 업로드하지 않는다.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.compare_best import find_sequences  # noqa: E402
from tools.record_burst import EVAL_ROOT, load_sequence  # noqa: E402
from walnut.analysis import DETECT_MODES, BurstAnalyzer, detect_tiles  # noqa: E402

MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "face_landmarker.task"
MODES = DETECT_MODES
TOTAL = "전체"
CSV_HEADER = ["시퀀스", "전략", "프레임 수", "얼굴 찾은 비율", "프레임당 얼굴 수", "평균 ms", "최대 ms"]
# 디버그 그림의 박스 색 (RGB)
_COLORS = {"full": (255, 80, 80), "halves": (80, 200, 255), "full+halves": (120, 255, 120)}


def stats(per_frame: list[tuple[int, float]]) -> dict:
    """[(얼굴 수, ms)] → 프레임 수 · 찾은 비율 · 평균 얼굴 수 · 평균 / 최대 ms."""
    n = len(per_frame)
    if n == 0:
        return {"frames": 0, "found": 0.0, "faces": 0.0, "ms_mean": 0.0, "ms_max": 0.0}
    return {
        "frames": n,
        "found": sum(1 for k, _ in per_frame if k > 0) / n,
        "faces": sum(k for k, _ in per_frame) / n,
        "ms_mean": sum(ms for _, ms in per_frame) / n,
        "ms_max": max(ms for _, ms in per_frame),
    }


def _row(name: str, mode: str, s: dict) -> list:
    return [name, mode, s["frames"], f"{s['found']:.3f}", f"{s['faces']:.2f}",
            f"{s['ms_mean']:.1f}", f"{s['ms_max']:.1f}"]


def format_line(name: str, mode: str, s: dict) -> str:
    return (f"{name}  {mode:<11}  프레임 {s['frames']}  얼굴 찾음 {s['found'] * 100:.0f}%  "
            f"평균 얼굴 {s['faces']:.2f}  평균 {s['ms_mean']:.0f}ms  최대 {s['ms_max']:.0f}ms")


def draw_debug(rgb, faces, mode: str, path: Path) -> None:
    """얼굴 박스와 (조각 전략이면) 조각 경계를 그려 JPEG 로 쓴다. 입력 rgb 는 고치지 않는다."""
    import cv2

    img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    h, w = img.shape[:2]
    r, g, b = _COLORS.get(mode, (255, 255, 0))
    color = (b, g, r)
    for name, x0, x1 in detect_tiles(w, mode):  # 조각 경계: 왼쪽 조각의 끝 · 오른쪽 조각의 시작
        x = {"left": x1 - 1, "right": x0}.get(name)
        if x is not None:
            cv2.line(img, (x, 0), (x, h - 1), (200, 200, 200), 1)
    thick = max(1, round(min(w, h) / 300))
    for f in faces:
        x0, y0, x1, y1 = f.box
        cv2.rectangle(img, (round(x0 * w), round(y0 * h)), (round(x1 * w), round(y1 * h)), color, thick)
    cv2.putText(img, f"{mode}  faces={len(faces)}", (8, max(16, h // 20)), cv2.FONT_HERSHEY_SIMPLEX,
                max(0.4, h / 900), color, thick)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".jpg", img)  # cv2.imwrite 는 Windows 에서 한글이 든 경로에 쓰지 못한다
    if ok:
        path.write_bytes(buf.tobytes())


def compare_sequence(detector, seq_dir: Path, debug_dir: Path | None = None) -> dict:
    """한 시퀀스를 전략마다 돌린다. {"name", "per_mode": {mode: [(얼굴 수, ms)]}}."""
    frames, _, meta = load_sequence(seq_dir)
    files = [e["file"] for e in meta["frames"]]
    rgbs = [f.rgb for f in frames]
    per_mode = {}
    for mode in MODES:
        res = detector.detect_frames(rgbs, mode).result()
        per_mode[mode] = [(len(faces), float(ms)) for faces, ms in res]
        if debug_dir is not None:
            for name, rgb, (faces, _) in zip(files, rgbs, res):
                draw_debug(rgb, faces, mode, Path(debug_dir) / seq_dir.name / f"{Path(name).stem}_{mode}.jpg")
    return {"name": seq_dir.name, "per_mode": per_mode}


def write_csv(path: Path, rows: list[list]) -> None:
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        w.writerows(rows)


def run(root: Path, detector, out=print, debug_dir: Path | None = None) -> list[dict]:
    root = Path(root)
    results, rows = [], []
    for d in find_sequences(root):
        try:
            r = compare_sequence(detector, d, debug_dir)
        except Exception as exc:  # 시퀀스 하나가 깨져도 나머지는 계속한다
            out(f"{d.name}  건너뜀: {exc}")
            continue
        results.append(r)
        for mode in MODES:
            s = stats(r["per_mode"][mode])
            rows.append(_row(r["name"], mode, s))
            out(format_line(r["name"], mode, s))
    if not results:
        out(f"비교할 시퀀스가 없습니다: {root}")
        return results
    for mode in MODES:
        s = stats([x for r in results for x in r["per_mode"][mode]])
        rows.append(_row(TOTAL, mode, s))
        out(format_line(TOTAL, mode, s))
    write_csv(root / "compare_detect.csv", rows)
    out(f"전략별 수치를 썼습니다: {root / 'compare_detect.csv'}")
    if debug_dir is not None:
        out(f"박스를 그린 그림을 썼습니다 (얼굴 사진이니 확인 뒤 지우세요): {debug_dir}")
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="검출 비교 도구 (로컬 파일만 읽고 아무것도 업로드하지 않는다)")
    ap.add_argument("--root", type=Path, default=EVAL_ROOT, help="시퀀스 폴더들이 있는 곳 (기본 booth/eval_data)")
    ap.add_argument("--debug-dir", type=Path, default=None,
                    help="프레임마다 전략별 얼굴 박스를 그린 JPEG 를 쓸 폴더 (원본 얼굴 사진이 담긴다, 기본 끔)")
    args = ap.parse_args(argv)
    analyzer = BurstAnalyzer(MODEL_PATH)
    if not analyzer.available:
        print(f"얼굴 모델이 없습니다: {MODEL_PATH} (tools/download_models.py)")
        return 1
    try:
        analyzer.warm()  # 모델 불러오기를 첫 시퀀스의 ms 에 넣지 않는다
        run(args.root, analyzer, debug_dir=args.debug_dir)
    finally:
        analyzer.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
