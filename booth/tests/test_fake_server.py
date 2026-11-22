from __future__ import annotations

import hashlib
import hmac
import io
import json

import requests
from PIL import Image

from walnut.settings import clamp_settings


def test_fake_server_routes(fake_server):
    fake_server.route("GET", "/x", lambda req: (200, {"ETag": '"v1"'}, {"a": 1}))
    r = requests.get(fake_server.url + "/x")
    assert r.json() == {"a": 1} and fake_server.requests[0].path == "/x"


def test_fake_server_unrouted_404_and_body(fake_server):
    fake_server.route("POST", "/y", lambda req: (201, {}, req.body))
    assert requests.get(fake_server.url + "/none").status_code == 404
    r = requests.post(fake_server.url + "/y", data=b"abc")
    assert r.status_code == 201 and r.content == b"abc"


def test_make_bundle_shape(make_bundle):
    raw, assets = make_bundle()
    b = json.loads(raw)
    assert b["version"] == 1 and b["event"]["id"] == 1
    assert b["settings"]["admin"]["pin_hash"] == hmac.new(b"k" * 32, b"482916", "sha256").hexdigest()
    assert clamp_settings(b["settings"]) == b["settings"]
    f = b["frames"][0]
    assert (f["width"], f["height"]) == (400, 600) and [s["shot"] for s in f["slots"]] == [0, 1, 2, 3]
    img = Image.open(io.BytesIO(assets[f["asset"]]))
    assert img.size == (400, 600) and img.mode == "RGBA"
    assert img.getpixel((100, 160))[3] == 0  # 구멍은 투명
    assert img.getpixel((5, 5))[3] == 255
    for a in b["assets"]:
        assert hashlib.sha256(assets[a["sha256"]]).hexdigest() == a["sha256"] and a["size"] == len(assets[a["sha256"]])


def test_make_bundle_patch_and_version(make_bundle):
    raw, _ = make_bundle(version=3, event_id=7, settings_patch={"capture": {"countdown_sec": 5}})
    b = json.loads(raw)
    assert b["version"] == 3 and b["event"]["id"] == 7 and b["settings"]["capture"]["countdown_sec"] == 5
    assert b["settings"]["capture"]["between_sec"] == 2
