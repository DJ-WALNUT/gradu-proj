"""E2E 용 실제 서버 하네스. 서버 venv 의 python 으로 실행한다 (부스 venv 에 서버 의존성을 섞지 않게).

  python server_harness.py --data <dir>

임시 DATA_DIR 로 서버를 만들고 관리자 API 로 행사(구멍 4개 프레임)를 게시한 뒤 페어링 코드를 발급한다.
준비되면 표준출력에 {"url": ..., "code": ...} 한 줄을 쓰고 요청을 받는다. 로그는 표준오류로.
표준입력 명령: `revoke` → 이 행사의 기기를 모두 폐기하고 {"revoked": n} 한 줄을 쓴다.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
import threading
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[3] / "server"
sys.path.insert(0, str(SERVER_DIR))

from PIL import Image  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from app import create_app  # noqa: E402
from app.auth import normalize_email  # noqa: E402
from app.db import get_db  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.timeutil import now  # noqa: E402

EMAIL = "e2e@x.com"
PASSWORD = "password1"
FRAME_W, FRAME_H = 400, 600
# 구멍 4개 (x, y, w, h) — 세로로 쌓은 3:4 칸
HOLES = [(50, 20 + i * 140, 90, 120) for i in range(4)]


def frame_png() -> bytes:
    img = Image.new("RGBA", (FRAME_W, FRAME_H), (40, 90, 200, 255))
    for x, y, w, h in HOLES:
        img.paste((0, 0, 0, 0), (x, y, x + w, y + h))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class Admin:
    """테스트 클라이언트로 관리자 API 를 부른다 (세션 쿠키 + CSRF)."""

    def __init__(self, app) -> None:
        self.c = app.test_client()
        r = self.c.post("/api/admin/auth/login", json={"email": EMAIL, "password": PASSWORD})
        self._ok(r, 200)
        self.csrf = r.json["csrf"]
        self._lock = threading.Lock()

    @staticmethod
    def _ok(r, *codes):
        if r.status_code not in codes:
            raise RuntimeError(f"관리자 API 실패 {r.status_code}: {r.get_data(as_text=True)}")
        return r

    def call(self, method: str, url: str, codes=(200,), json=None, data=None):
        with self._lock:
            r = self.c.open(url, method=method, json=json, data=data, headers={"X-CSRF-Token": self.csrf})
        return self._ok(r, *codes).json


def seed(app) -> int:
    """사용자·조직·owner 멤버십 (서버 tests/conftest.py 의 make_user·make_org·add_member 와 같은 SQL). org_id 반환."""
    with app.app_context():
        db = get_db()
        uid = db.execute(
            "INSERT INTO users (email, password_hash, is_superadmin, created_at) VALUES (?,?,?,?)",
            (normalize_email(EMAIL), hash_password(PASSWORD), 0, now()),
        ).lastrowid
        org = db.execute(
            "INSERT INTO organizations (name, slug, storage_quota_mb, max_ttl_hours, created_at)"
            " VALUES (?,?,?,?,?)",
            ("E2E", "e2e", 2048, 168, now()),
        ).lastrowid
        db.execute("INSERT INTO memberships (user_id, org_id, role) VALUES (?,?,?)", (uid, org, "owner"))
        return org


def publish_event(admin: Admin, org: int) -> int:
    ev = admin.call("POST", f"/api/admin/orgs/{org}/events", (201,), json={"name": "E2E 행사"})["id"]
    sha = admin.call("POST", f"/api/admin/orgs/{org}/assets", (200, 201),
                     data={"kind": "frame", "file": (io.BytesIO(frame_png()), "frame.png")})["sha256"]
    fid = admin.call("POST", f"/api/admin/events/{ev}/frames", (201,), json={"name": "기본", "asset": sha})["id"]
    slots = [{"id": f"s{i + 1}", "shot": i, "cx": x + w / 2, "cy": y + h / 2, "w": w, "h": h, "rot": 0,
              "ratio": "3:4"} for i, (x, y, w, h) in enumerate(HOLES)]
    admin.call("PATCH", f"/api/admin/frames/{fid}", json={"slots": slots})
    admin.call("POST", f"/api/admin/events/{ev}/publish")
    return ev


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def command_loop(admin: Admin, ev: int) -> None:
    for line in sys.stdin:
        cmd = line.strip()
        try:
            if cmd == "revoke":
                n = 0
                for d in admin.call("GET", f"/api/admin/events/{ev}/devices"):
                    if not d["revoked"]:
                        admin.call("POST", f"/api/admin/devices/{d['id']}/revoke")
                        n += 1
                emit({"revoked": n})
            elif cmd:
                emit({"error": f"모르는 명령: {cmd}"})
        except Exception as e:  # 명령 실패로 서버가 멈추면 안 된다
            logging.exception("명령 실패")
            emit({"error": str(e)})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    args = ap.parse_args()
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)

    app = create_app({
        "SECRET_KEY": "e2e" * 8, "DATA_DIR": args.data, "PUBLIC_URL": "", "SESSION_COOKIE_SECURE": False,
        "CLEANUP_INTERVAL": 0, "TRUSTED_PROXY_HOPS": 0,
    })
    org = seed(app)
    admin = Admin(app)
    ev = publish_event(admin, org)
    code = admin.call("POST", f"/api/admin/events/{ev}/devices", (201,), json={"name": "E2E 부스"})["code"]

    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=command_loop, args=(admin, ev), name="stdin", daemon=True).start()
    emit({"url": f"http://127.0.0.1:{server.server_port}", "code": code})
    server.serve_forever()


if __name__ == "__main__":
    main()
