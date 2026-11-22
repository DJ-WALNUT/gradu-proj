"""색 역할 테스트와 gen_expected.py 가 함께 쓰는 사례 목록 (한 곳에만 둔다)."""

import random

DEFAULT = {"primary": "#1b2550", "accent": "#e66e82", "bg_top": "#fff8f9", "bg_bottom": "#eaf4fb"}

HARD_CASES = [
    {"name": "연한 주요색", **DEFAULT, "primary": "#d8dce8"},
    {"name": "배경과 같은 강조색", **DEFAULT, "accent": "#fff8f9"},
    {"name": "어두운 배경 + 어두운 주요색", "primary": "#2a3050", "accent": "#e66e82",
     "bg_top": "#141821", "bg_bottom": "#20263a"},
    {"name": "채도 높은 노랑 강조", **DEFAULT, "accent": "#ffd400"},
    {"name": "위아래 배경 명도 차이 큼", **DEFAULT, "primary": "#595959",
     "bg_top": "#ffffff", "bg_bottom": "#5a5a5a"},
    {"name": "중간 명도 강조", **DEFAULT, "accent": "#7f7f7f"},
]


def random_cases(seed: int, n: int) -> list[dict]:
    """네 색을 무작위 hex 로 뽑은 사례 n 개 (seed 고정)."""
    rng = random.Random(seed)

    def color() -> str:
        return "#%02x%02x%02x" % (rng.randrange(256), rng.randrange(256), rng.randrange(256))

    return [{"name": f"무작위 {seed}-{i}", "primary": color(), "accent": color(),
             "bg_top": color(), "bg_bottom": color()} for i in range(n)]
