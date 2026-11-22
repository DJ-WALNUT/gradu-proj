"""부스 API 클라이언트. 서버 응답을 예외 종류로 나눠 호출자가 재시도·해제를 정한다."""

from __future__ import annotations

import hashlib
import math

import requests

from walnut.device import Device, decode_key

TIMEOUT = (5, 30)


class ApiError(Exception):
    pass


class Revoked(ApiError):
    """401: 서버가 이 기기를 해제했다."""


class NotPublished(ApiError):
    """404 not_published: 아직 게시된 번들이 없다."""


class Unreachable(ApiError):
    """연결 실패, 타임아웃, 5xx, 429: 나중에 다시 시도."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__(f"서버에 닿지 않음 (retry_after={retry_after})")
        self.retry_after = retry_after


class Rejected(ApiError):
    """그 밖의 4xx: 다시 시도해도 소용없다."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(f"거절됨 {status} {code}")
        self.status = status
        self.code = code


def _error_code(resp: requests.Response) -> str:
    try:
        v = resp.json().get("error", "")
        return v if isinstance(v, str) else ""
    except (ValueError, AttributeError):
        return ""


def _retry_after(resp: requests.Response) -> float | None:
    """초 단위 Retry-After. 유한한 0 이상 숫자가 아니면 None (nan·inf·음수는 무시)."""
    try:
        v = float(resp.headers["Retry-After"])
    except (KeyError, ValueError):
        return None
    return v if math.isfinite(v) and v >= 0 else None


def _check(resp: requests.Response, ok: tuple[int, ...] = (200,)) -> None:
    """ok 가 아닌 응답을 예외로 바꾼다."""
    s = resp.status_code
    if s in ok:
        return
    if s == 401:
        raise Revoked()
    if s == 429 or s >= 500:
        raise Unreachable(_retry_after(resp))
    code = _error_code(resp)
    if s == 404 and code == "not_published":
        raise NotPublished()
    raise Rejected(s, code)


def _request(sess, method: str, url: str, **kw) -> requests.Response:
    try:
        return sess.request(method, url, timeout=TIMEOUT, **kw)
    except requests.RequestException as e:
        raise Unreachable(None) from e


def pair(server_url: str, code: str, app_version: str) -> Device:
    """페어링 코드로 기기를 등록한다."""
    base = server_url.rstrip("/")
    with requests.Session() as sess:
        resp = _request(sess, "POST", f"{base}/api/booth/pair",
                        json={"code": code, "app_version": app_version})
    _check(resp)
    try:
        j = resp.json()
        return Device(base, j["device_token"], decode_key(j["bundle_key"]),
                      int(j["event"]["id"]), str(j["event"]["name"]))
    except (ValueError, KeyError, TypeError) as e:
        raise Rejected(resp.status_code, "bad_response") from e


class BoothApi:
    def __init__(self, device: Device, session: requests.Session | None = None) -> None:
        self.device = device
        self._base = device.server_url.rstrip("/") + "/api/booth"
        self._sess = session or requests.Session()
        self._auth = {"Authorization": f"Bearer {device.token}"}

    def _call(self, method: str, path: str, headers: dict | None = None, **kw) -> requests.Response:
        return _request(self._sess, method, self._base + path,
                        headers={**self._auth, **(headers or {})}, **kw)

    def get_bundle(self, etag: str | None) -> tuple[bytes, str] | None:
        """304 면 None, 200 이면 (원문 바이트, ETag 헤더 그대로)."""
        resp = self._call("GET", "/bundle", {"If-None-Match": etag} if etag else None)
        if resp.status_code == 304:
            return None
        _check(resp)
        return resp.content, resp.headers.get("ETag", "")

    def get_asset(self, sha: str) -> bytes:
        resp = self._call("GET", f"/assets/{sha}")
        _check(resp)
        if hashlib.sha256(resp.content).hexdigest() != sha:
            raise Rejected(0, "sha_mismatch")
        return resp.content

    def heartbeat(self, payload: dict) -> None:
        _check(self._call("POST", "/heartbeat", json=payload), ok=(200, 204))

    def upload_photo(self, token: str, jpeg: bytes) -> None:
        """201·409 는 성공. 503·507 은 Unreachable 로 올라가 재시도된다."""
        resp = self._call("POST", "/photos", data={"token": token},
                          files={"file": (f"{token}.jpg", jpeg, "image/jpeg")})
        _check(resp, ok=(200, 201, 409))
