"""Serving the live viewer build at / (SLICEPOINT_UI_DIR)."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import AUTH, TOKEN, make_client, make_settings
from slicepoint_api import create_app
from slicepoint_api.settings import Settings, SettingsError
from slicepoint_api.ui import UI_CSP, bundled_ui_dir, resolve_ui_file

INDEX = b"<!doctype html><title>SlicePoint</title><script type=module src=/assets/app.js></script>"


@pytest.fixture()
def dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    data = tmp_path / "data"
    data.mkdir()
    ui = tmp_path / "ui"
    (ui / "assets").mkdir(parents=True)
    (ui / "index.html").write_bytes(INDEX)
    (ui / "assets" / "app.js").write_text("console.log(1)")
    (ui / "assets" / "app.css").write_text("body{}")
    (ui / "assets" / ".hidden.js").write_text("hidden")
    (ui / "notes.txt").write_text("not an asset")
    (tmp_path / "secret.txt").write_text("outside the ui folder")
    (ui / "assets" / "link.js").symlink_to(tmp_path / "secret.txt")
    return data, tmp_path / "results", ui


def test_no_ui_routes_when_unset(dirs: tuple[Path, Path, Path]) -> None:
    data, results, _ = dirs
    with make_client(data, results) as c:
        assert c.get("/").status_code == 401
        assert c.get("/assets/app.js").status_code == 401
        assert c.get("/", headers=AUTH).status_code == 404
        assert c.get("/index.html", headers=AUTH).status_code == 404


def test_ui_is_served_without_auth_with_the_live_csp(dirs: tuple[Path, Path, Path]) -> None:
    data, results, ui = dirs
    with make_client(data, results, ui_dir=ui) as c:
        for path in ("/", "/index.html"):
            r = c.get(path)
            assert r.status_code == 200 and r.content == INDEX
            assert r.headers["content-type"].startswith("text/html")
            assert r.headers["content-security-policy"] == UI_CSP
            assert r.headers["x-frame-options"] == "DENY" and r.headers["x-content-type-options"] == "nosniff"
        assert c.head("/").status_code == 200
        r = c.get("/assets/app.js")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
        assert r.headers["content-security-policy"] == UI_CSP
        assert c.get("/assets/app.css").headers["content-type"].startswith("text/css")
        # The rest of the API is still locked.
        assert c.get("/v1/datasets").status_code == 401
        assert c.get("/notes.txt").status_code == 401
        assert c.post("/").status_code == 401


def test_live_csp_allows_only_same_origin() -> None:
    parts = dict(p.strip().split(" ", 1) for p in UI_CSP.split(";"))
    assert parts["default-src"] == "'none'" and parts["connect-src"] == "'self'"
    assert parts["frame-ancestors"] == "'none'" and parts["base-uri"] == "'none'"
    assert parts["form-action"] == "'self'"
    assert "unsafe" not in UI_CSP and "http" not in UI_CSP


@pytest.mark.parametrize("path", [
    "/assets/..%2Fsecret.txt", "/assets/..%2F..%2Fsecret.txt", "/assets/%2e%2e/secret.txt",
    "/assets/.hidden.js", "/assets/link.js", "/assets/", "/assets/nope.js", "/assets/..%5Cnotes.txt",
    "/assets/%2Fetc%2Fpasswd",
])
def test_ui_path_traversal_is_blocked(dirs: tuple[Path, Path, Path], path: str) -> None:
    data, results, ui = dirs
    with make_client(data, results, ui_dir=ui) as c:
        r = c.get(path)
        assert r.status_code == 404, path  # reached the UI route and was refused there
        assert b"outside the ui folder" not in r.content and b"hidden" not in r.content


def test_resolve_ui_file(dirs: tuple[Path, Path, Path]) -> None:
    ui = dirs[2]
    assert resolve_ui_file(ui, "assets/app.js") == (ui / "assets" / "app.js").resolve()
    for bad in ("../secret.txt", "assets/../../secret.txt", "assets/link.js", "assets/.hidden.js",
                "/etc/passwd", "assets//app.js", "assets", "", "assets\\..\\notes.txt"):
        assert resolve_ui_file(ui, bad) is None, bad


def test_ui_dir_must_hold_index_html(dirs: tuple[Path, Path, Path]) -> None:
    data, results, ui = dirs
    with pytest.raises(SettingsError, match="index.html"):
        create_app(make_settings(data, results, ui_dir=ui / "assets"))


def test_from_env_reads_ui_and_session_settings(dirs: tuple[Path, Path, Path]) -> None:
    data, results, ui = dirs
    base = {"SLICEPOINT_SERVICE_TOKEN": TOKEN, "SLICEPOINT_DATA_ROOT": str(data),
            "SLICEPOINT_RESULTS_DIR": str(results)}
    s = Settings.from_env(base)
    assert s.ui_dir == bundled_ui_dir() and s.ui_dir is not None
    assert s.cookie_secure is True and s.session_ttl_seconds == 8 * 3600
    assert Settings.from_env({**base, "SLICEPOINT_UI": "off"}).ui_dir is None
    assert Settings.from_env({**base, "SLICEPOINT_UI": "0", "SLICEPOINT_UI_DIR": str(ui)}).ui_dir is None
    s = Settings.from_env({**base, "SLICEPOINT_UI_DIR": str(ui), "SLICEPOINT_COOKIE_SECURE": "0",
                           "SLICEPOINT_SESSION_TTL_SECONDS": "3600"})
    assert s.ui_dir == ui and s.cookie_secure is False and s.session_ttl_seconds == 3600


def test_from_env_without_a_bundled_ui_names_the_fix(dirs: tuple[Path, Path, Path],
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    data, results, _ = dirs
    monkeypatch.setattr("slicepoint_api.ui.bundled_ui_dir", lambda: None)
    base = {"SLICEPOINT_SERVICE_TOKEN": TOKEN, "SLICEPOINT_DATA_ROOT": str(data),
            "SLICEPOINT_RESULTS_DIR": str(results)}
    with pytest.raises(SettingsError, match="no bundled web UI.*SLICEPOINT_UI=off"):
        Settings.from_env(base)
    assert Settings.from_env({**base, "SLICEPOINT_UI": "off"}).ui_dir is None
