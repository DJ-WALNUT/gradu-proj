"""expected.json 생성 — JS 구현(Task 4)이 같은 값을 내는지 대조하는 기준 파일.

사용: server/.venv/bin/python shared/booth-design/tools/gen_expected.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from booth_tokens import load, resolve_roles  # noqa: E402
from cases import DEFAULT, HARD_CASES, random_cases  # noqa: E402

KEYS = ("primary", "accent", "bg_top", "bg_bottom")


def main() -> None:
    tokens = load()
    named = [{"name": "기본값", **DEFAULT}] + HARD_CASES + random_cases(seed=7, n=12)
    cases = []
    for c in named:
        event = {k: c[k] for k in KEYS}
        cases.append({"name": c["name"], "event": event, "roles": resolve_roles(tokens, event)})
    (ROOT / "expected.json").write_text(
        json.dumps({"version": 1, "cases": cases}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"expected.json: {len(cases)}개")


if __name__ == "__main__":
    main()
