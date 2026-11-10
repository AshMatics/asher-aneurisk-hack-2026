"""Authentication, body cap and response hardening (no practice data needed)."""

from __future__ import annotations

import asyncio
from collections.abc import MutableMapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from conftest import AUTH, TOKEN, make_client
from slicepoint_api.security import BAD_AUTH_PER_MINUTE, SecurityMiddleware
from slicepoint_api.settings import Settings, SettingsError


@pytest.fixture()
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    data = tmp_path / "data"
    data.mkdir()
    return data, tmp_path / "results"


def test_healthz_needs_no_token(dirs: tuple[Path, Path]) -> None:
    with make_client(*dirs) as c:
        r = c.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "alive"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN},
                                     {"Authorization": f"Bearer {TOKEN}x"}])
def test_missing_or_wrong_token_is_401(dirs: tuple[Path, Path], headers: dict[str, str]) -> None:
    with make_client(*dirs) as c:
        for path in ("/v1/checks", "/v1/datasets", "/v1/assessments", "/v1/references", "/nope"):
            r = c.get(path, headers=headers)
            assert r.status_code == 401, path
            assert r.json() == {"detail": "Invalid or missing bearer token"}


def test_401_before_the_body_is_parsed(dirs: tuple[Path, Path]) -> None:
    with make_client(*dirs) as c:
        r = c.post("/v1/assessments", content=b"{not json", headers={"Content-Type": "application/json"})
        assert r.status_code == 401  # not 422: the body was never parsed
        r = c.post("/v1/assessments", content=b"{not json", headers={**AUTH, "Content-Type": "application/json"})
        assert r.status_code == 422


def test_middleware_never_calls_receive_without_a_token() -> None:
    """ASGI level: an unauthenticated request is answered without reading the body."""
    called: list[str] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        called.append("app")

    async def receive() -> dict[str, Any]:
        called.append("receive")
        return {"type": "http.request", "body": b"x" * 10, "more_body": False}

    sent: list[MutableMapping[str, Any]] = []

    async def send(message: MutableMapping[str, Any]) -> None:
        sent.append(message)

    mw = SecurityMiddleware(app, token=TOKEN, max_body_bytes=100)
    scope = {"type": "http", "method": "POST", "path": "/v1/assessments", "headers": [], "client": ("1.2.3.4", 1)}
    asyncio.run(mw(scope, receive, send))
    assert called == []
    assert sent[0]["status"] == 401


def test_repeated_bad_tokens_are_throttled(dirs: tuple[Path, Path]) -> None:
    with make_client(*dirs) as c:
        codes = [c.get("/v1/checks", headers={"Authorization": "Bearer nope"}).status_code
                 for _ in range(BAD_AUTH_PER_MINUTE + 1)]
        assert codes[-1] == 429 and set(codes[:-1]) == {401}
        assert c.get("/v1/checks", headers=AUTH).status_code == 200


def test_short_token_refuses_to_start(dirs: tuple[Path, Path]) -> None:
    data, results = dirs
    with pytest.raises(ValidationError):
        Settings.model_validate({"token": "x" * 31, "data_root": data, "results_dir": results})
    env = {"SLICEPOINT_SERVICE_TOKEN": "short-secret", "SLICEPOINT_DATA_ROOT": str(data),
           "SLICEPOINT_RESULTS_DIR": str(results)}
    with pytest.raises(SettingsError) as info:
        Settings.from_env(env)
    assert "short-secret" not in str(info.value) and "32" in str(info.value)


def test_missing_env_is_a_one_line_error() -> None:
    with pytest.raises(SettingsError, match="SLICEPOINT_SERVICE_TOKEN"):
        Settings.from_env({})


def test_from_env_reads_everything(dirs: tuple[Path, Path]) -> None:
    data, results = dirs
    s = Settings.from_env({"SLICEPOINT_SERVICE_TOKEN": TOKEN, "SLICEPOINT_DATA_ROOT": str(data),
                           "SLICEPOINT_RESULTS_DIR": str(results), "SLICEPOINT_MAX_CONCURRENT_JOBS": "3",
                           "SLICEPOINT_ENABLE_DOCS": "1"})
    assert s.max_concurrent_jobs == 3 and s.enable_docs and s.host == "127.0.0.1"
    assert TOKEN not in repr(s)


def test_results_dir_inside_data_root_is_refused(tmp_path: Path) -> None:
    from slicepoint_api import create_app
    from conftest import make_settings

    with pytest.raises(SettingsError):
        create_app(make_settings(tmp_path, tmp_path / "results"))


def test_body_cap(dirs: tuple[Path, Path]) -> None:
    with make_client(*dirs, max_body_bytes=200) as c:
        r = c.post("/v1/assessments", content=b"{" + b" " * 500 + b"}",
                   headers={**AUTH, "Content-Type": "application/json"})
        assert r.status_code == 413


def test_docs_disabled_by_default(dirs: tuple[Path, Path]) -> None:
    with make_client(*dirs) as c:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert c.get(path, headers=AUTH).status_code == 404, path
    with make_client(*dirs, enable_docs=True) as c:
        assert c.get("/openapi.json", headers=AUTH).status_code == 200
        assert c.get("/openapi.json").status_code == 401


def test_checks_lists_the_registry(dirs: tuple[Path, Path]) -> None:
    with make_client(*dirs) as c:
        r = c.get("/v1/checks", headers=AUTH)
    assert r.status_code == 200
    ids = [d["id"] for d in r.json()]
    assert len(ids) == 5 and "repeats" in ids


def test_validation_errors_do_not_echo_input(dirs: tuple[Path, Path]) -> None:
    with make_client(*dirs) as c:
        r = c.post("/v1/assessments", headers=AUTH,
                   json={"dataset": "x", "site_id": "Secret Hospital Name", "reference_id": "ref-a"})
    assert r.status_code == 422
    assert "Secret Hospital Name" not in r.text
    assert all(set(e) == {"loc", "msg", "type"} for e in r.json()["detail"])
