"""여러 OS 에서 돌기 위한 것 — 앱 버전(설치 zip 의 VERSION), macOS 이동식 드라이브."""

from __future__ import annotations

from pathlib import Path

import walnut
from walnut import version
from walnut.scenes import import_zip


def test_app_version_without_version_file(tmp_path, monkeypatch):
    monkeypatch.setattr(version, "VERSION_FILE", tmp_path / "VERSION")
    assert version.app_version() == walnut.__version__


def test_app_version_from_installed_zip(tmp_path, monkeypatch):
    f = tmp_path / "VERSION"
    f.write_text("0.1.0+a1b2c3d\n", encoding="utf-8")
    monkeypatch.setattr(version, "VERSION_FILE", f)
    assert version.app_version() == "0.1.0+a1b2c3d"


def test_app_version_ignores_garbage(tmp_path, monkeypatch):
    f = tmp_path / "VERSION"
    f.write_text("x" * 500, encoding="utf-8")
    monkeypatch.setattr(version, "VERSION_FILE", f)
    assert version.app_version() == walnut.__version__


def test_mac_removable_roots_lists_volumes_except_system(tmp_path, monkeypatch):
    vols = tmp_path / "Volumes"
    (vols / "USB DISK").mkdir(parents=True)
    (vols / "Macintosh HD").mkdir()  # 실제 Mac 에서는 / 를 가리키는 링크
    (vols / ".hidden").mkdir()
    monkeypatch.setattr(import_zip.sys, "platform", "darwin")
    monkeypatch.setattr(import_zip, "MAC_VOLUMES", vols)
    monkeypatch.setattr(import_zip, "_is_system_volume", lambda p: p.name == "Macintosh HD")
    assert import_zip.removable_roots() == [vols / "USB DISK"]


def test_mac_removable_roots_missing_volumes_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(import_zip.sys, "platform", "darwin")
    monkeypatch.setattr(import_zip, "MAC_VOLUMES", tmp_path / "nope")
    assert import_zip.removable_roots() == []


def test_other_platform_has_no_removable_roots(monkeypatch):
    monkeypatch.setattr(import_zip.sys, "platform", "linux")
    assert import_zip.removable_roots() == []


def test_sync_and_pairing_report_app_version(monkeypatch):
    import walnut.scenes.pairing as pairing
    import walnut.sync as sync

    src = Path(sync.__file__).read_text(encoding="utf-8") + Path(pairing.__file__).read_text(encoding="utf-8")
    assert "walnut.__version__" not in src
    assert "app_version()" in src
