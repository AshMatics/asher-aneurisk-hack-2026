"""Browser sessions: token -> HttpOnly cookie, CSRF header, logout, expiry (no practice data needed)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import AUTH, TOKEN, make_settings
from slicepoint_api import create_app
from slicepoint_api.security import API_CSP, BAD_AUTH_PER_MINUTE, CSRF_HEADER, SessionStore

CSRF = {CSRF_HEADER: "1"}
SECURE_NAME = "__Host-slicepoint-session"
PLAIN_NAME = "slicepoint-session"


@pytest.fixture()
def dirs(tmp_path: Path) -> tuple[Path, Path]:
    data = tmp_path / "data"
    (data / "site_x").mkdir(parents=True)
    (data / "site_x" / "features.parquet").write_bytes(b"")
    return data, tmp_path / "results"


def _client(dirs: tuple[Path, Path], **kw: Any) -> TestClient:
    # https so the client's cookie jar sends the Secure cookie back.
    secure = kw.get("cookie_secure", True)
    return TestClient(create_app(make_settings(*dirs, **kw)),
                      base_url="https://testserver" if secure else "http://testserver")


@pytest.fixture()
def client(dirs: tuple[Path, Path]) -> Iterator[TestClient]:
    with _client(dirs) as c:
        yield c


def _sign_in(c: TestClient) -> str:
    r = c.post("/v1/session", json={"token": TOKEN}, headers=CSRF)
    assert r.status_code == 200, r.text
    sid = c.cookies.get(SECURE_NAME) or c.cookies.get(PLAIN_NAME)
    assert isinstance(sid, str) and sid
    return sid


def test_sign_in_sets_a_hardened_cookie_that_is_not_the_token(client: TestClient) -> None:
    r = client.post("/v1/session", json={"token": TOKEN}, headers=CSRF)
    assert r.status_code == 200
    body = r.json()
    assert body["signed_in"] is True and body["expires_at"]
    raw = r.headers["set-cookie"]
    flags = {p.strip().split("=")[0].lower() for p in raw.split(";")}
    assert raw.startswith(f"{SECURE_NAME}=")
    assert {"httponly", "secure", "path", "max-age", "samesite"} <= flags
    assert "samesite=strict" in raw.lower() and "path=/" in raw.lower() and "max-age=28800" in raw.lower()
    assert "domain" not in flags
    sid = client.cookies.get(SECURE_NAME)
    assert sid and sid != TOKEN and TOKEN not in sid and sid not in TOKEN and len(sid) >= 40
    assert TOKEN not in raw and TOKEN not in r.text
    # The server keeps only a hash of the session id.
    store: SessionStore = client.app.state.auth.sessions  # type: ignore[attr-defined]
    assert sid not in store._sessions and TOKEN not in str(store._sessions)  # noqa: SLF001


def test_two_sign_ins_get_different_session_ids(client: TestClient) -> None:
    first = _sign_in(client)
    client.cookies.clear()
    assert _sign_in(client) != first


def test_secure_flag_can_be_switched_off_for_plain_http(dirs: tuple[Path, Path]) -> None:
    with _client(dirs, cookie_secure=False, session_ttl_seconds=600) as c:
        r = c.post("/v1/session", json={"token": TOKEN}, headers=CSRF)
        raw = r.headers["set-cookie"]
        assert raw.startswith(f"{PLAIN_NAME}=") and "secure" not in raw.lower()
        assert "httponly" in raw.lower() and "max-age=600" in raw.lower()
        assert c.get("/v1/datasets").json() == {"datasets": ["site_x"]}


def test_cookie_works_for_get(client: TestClient) -> None:
    assert client.get("/v1/session").json() == {"signed_in": False, "expires_at": None}
    assert client.get("/v1/datasets").status_code == 401
    _sign_in(client)
    assert client.get("/v1/session").json()["signed_in"] is True
    r = client.get("/v1/datasets")
    assert r.status_code == 200 and r.json() == {"datasets": ["site_x"]}
    assert client.get("/v1/assessments").status_code == 200


def test_cookie_unsafe_request_needs_the_csrf_header(client: TestClient) -> None:
    _sign_in(client)
    body = {"dataset": "site_x", "site_id": "site_x", "reference_id": "ref-nope"}
    r = client.post("/v1/assessments", json=body)
    assert r.status_code == 403 and CSRF_HEADER in r.json()["detail"]
    assert client.post("/v1/assessments", json=body, headers={CSRF_HEADER: "0"}).status_code == 403
    r = client.post("/v1/assessments", json=body, headers=CSRF)
    assert r.status_code == 404  # past auth and CSRF: the stored reference does not exist


def test_bearer_needs_no_csrf_header(client: TestClient) -> None:
    body = {"dataset": "site_x", "site_id": "site_x", "reference_id": "ref-nope"}
    assert client.post("/v1/assessments", json=body, headers=AUTH).status_code == 404


def test_session_create_needs_the_csrf_header(client: TestClient) -> None:
    r = client.post("/v1/session", json={"token": TOKEN})
    assert r.status_code == 403 and "set-cookie" not in r.headers


def test_wrong_token_is_401_and_counts_towards_the_rate_limit(client: TestClient) -> None:
    codes = [client.post("/v1/session", json={"token": "wrong" * 8}, headers=CSRF).status_code
             for _ in range(BAD_AUTH_PER_MINUTE // 2)]
    codes += [client.get("/v1/checks", headers={"Authorization": "Bearer nope"}).status_code
              for _ in range(BAD_AUTH_PER_MINUTE - len(codes))]
    assert set(codes) == {401}
    # The shared budget is used up: both routes now answer 429, even with the right token.
    assert client.post("/v1/session", json={"token": "wrong"}, headers=CSRF).status_code == 429
    r = client.post("/v1/session", json={"token": TOKEN}, headers=CSRF)
    assert r.status_code == 429 and r.headers["retry-after"] == "60" and "set-cookie" not in r.headers
    assert client.get("/v1/checks", headers={"Authorization": "Bearer nope"}).status_code == 429


def test_bad_session_cookie_is_401_and_counts(client: TestClient) -> None:
    client.cookies.set(SECURE_NAME, "made-up-session-id")
    codes = [client.get("/v1/datasets").status_code for _ in range(BAD_AUTH_PER_MINUTE + 1)]
    assert set(codes[:-1]) == {401} and codes[-1] == 429


def test_session_body_is_capped_and_never_echoed(client: TestClient) -> None:
    r = client.post("/v1/session", content=b'{"token": "' + b"a" * 2000 + b'"}',
                    headers={**CSRF, "Content-Type": "application/json"})
    assert r.status_code == 413
    secret = "s3cret-" + "z" * 600
    r = client.post("/v1/session", json={"token": secret}, headers=CSRF)
    assert r.status_code in (413, 422) and secret not in r.text
    r = client.post("/v1/session", json={"token": "x" * 513}, headers=CSRF)
    assert r.status_code == 422 and "xxxx" not in r.text


def test_get_session_ignores_the_authorization_header(client: TestClient) -> None:
    """GET /v1/session is open, so it must not become an unthrottled token oracle."""
    assert client.get("/v1/session", headers=AUTH).json()["signed_in"] is False
    for _ in range(BAD_AUTH_PER_MINUTE + 2):
        assert client.get("/v1/session", headers={"Authorization": "Bearer x"}).status_code == 200


def test_logout(client: TestClient) -> None:
    sid = _sign_in(client)
    assert client.delete("/v1/session").status_code == 403  # CSRF header required
    r = client.delete("/v1/session", headers=CSRF)
    assert r.status_code == 204
    raw = r.headers["set-cookie"].lower()
    assert raw.startswith(f"{SECURE_NAME.lower()}=") and ("max-age=0" in raw or "expires=" in raw)
    assert client.get("/v1/session").json()["signed_in"] is False
    # The old id is dead server-side even if a client kept it.
    client.cookies.set(SECURE_NAME, sid)
    assert client.get("/v1/datasets").status_code == 401


def test_session_expires(client: TestClient) -> None:
    _sign_in(client)
    assert client.get("/v1/datasets").status_code == 200
    store: SessionStore = client.app.state.auth.sessions  # type: ignore[attr-defined]
    store.clock = lambda: time.time() + 8 * 3600 + 1
    assert client.get("/v1/datasets").status_code == 401
    assert client.get("/v1/session").json()["signed_in"] is False
    assert len(store) == 0


def test_session_store_is_bounded() -> None:
    store = SessionStore(60, max_sessions=3)
    ids = [store.create()[0] for _ in range(5)]
    assert len(store) == 3
    assert store.expires_at(ids[0]) is None and store.expires_at(ids[-1]) is not None
    assert store.expires_at("x" * 1000) is None and store.expires_at(None) is None


def test_api_responses_carry_a_deny_all_csp(client: TestClient) -> None:
    r = client.get("/v1/datasets", headers=AUTH)
    assert r.headers["content-security-policy"] == API_CSP
    assert client.get("/healthz").headers["content-security-policy"] == API_CSP
