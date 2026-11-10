"""Authentication before the body is read, a body size cap and response hardening.

The same pattern as the segmentation worker (``slicepoint/segmentation/slicepoint_model/
security.py``): a pure ASGI middleware checks credentials with :func:`hmac.compare_digest`
before FastAPI parses anything, so an unauthenticated client never gets a request body
parsed or validated.

Two kinds of credential are accepted:

* ``Authorization: Bearer <token>`` for the CLI, scripts and FORGE (unchanged from M4).
* A browser session cookie for the live viewer. ``POST /v1/session`` exchanges the token
  for an opaque random session id (never the token itself), kept server-side in memory
  with an expiry. The cookie is ``HttpOnly; SameSite=Strict; Path=/`` and ``Secure``
  unless switched off for plain-http loopback development. A cookie-authenticated
  request with an unsafe method must also carry ``X-SlicePoint-CSRF: 1``; a bearer
  request does not need it.

Open routes: ``GET /healthz``, ``GET /v1/session`` (says whether the cookie is a live
session), ``POST``/``DELETE /v1/session`` (CSRF header required; the token is checked
by the route and failures count towards the same rate limit) and, only when the live
UI is configured, the UI shell and its static assets.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import secrets
import threading
import time
from collections import OrderedDict, defaultdict, deque
from collections.abc import Awaitable, Callable, Iterable, MutableMapping
from typing import Any

from starlette.responses import JSONResponse

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

BAD_AUTH_PER_MINUTE = 10
"""Failed authentication attempts allowed per client address per minute."""

SESSION_PATH = "/v1/session"
CSRF_HEADER = "X-SlicePoint-CSRF"
"""Custom header every cookie-authenticated unsafe request must carry (value ``1``)."""
SESSION_BODY_MAX_BYTES = 1024
"""Cap on the ``POST /v1/session`` body (it holds only the token)."""
MAX_SESSIONS = 1024
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
"""Content-Security-Policy for every response that does not set its own."""

_HARDENING_HEADERS = [
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
]


def cookie_name(secure: bool) -> str:
    """``__Host-`` makes the browser insist on Secure, Path=/ and no Domain. It cannot be
    used without Secure, so plain-http development gets an unprefixed name."""
    return "__Host-slicepoint-session" if secure else "slicepoint-session"


def read_cookie(headers: Iterable[tuple[bytes, bytes]], name: str) -> str | None:
    """The value of cookie ``name`` from every ``Cookie`` header, or None."""
    for key, value in headers:
        if key != b"cookie":
            continue
        for part in value.decode("latin-1").split(";"):
            k, sep, v = part.strip().partition("=")
            if sep and k == name:
                return v.strip()
    return None


class RateLimiter:
    """Counts failed authentication attempts per client address over a sliding minute."""

    def __init__(self, per_minute: int = BAD_AUTH_PER_MINUTE) -> None:
        self.per_minute = per_minute
        self._attempts: defaultdict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _queue(self, peer: str, now: float) -> deque[float]:
        queue = self._attempts[peer[:128]]
        while queue and queue[0] <= now - 60:
            queue.popleft()
        return queue

    def blocked(self, peer: str) -> bool:
        """True if ``peer`` has used up its failures for this minute (nothing is recorded)."""
        with self._lock:
            return len(self._queue(peer, time.monotonic())) >= self.per_minute

    def register_failure(self, peer: str) -> bool:
        """Record a failure. False means the peer is over the limit (answer 429)."""
        now = time.monotonic()
        with self._lock:
            queue = self._queue(peer, now)
            if len(queue) >= self.per_minute:
                return False
            queue.append(now)
            if len(self._attempts) > 2048:  # no unbounded remote-address map
                self._attempts = defaultdict(deque, {peer[:128]: queue})
            return True


class SessionStore:
    """Browser sessions held in memory: sha256(session id) -> expiry (unix seconds).

    Session ids are 256-bit random values from :mod:`secrets`, unrelated to the token.
    Only their hash is kept, so a memory dump does not hand out live cookies. Sessions
    are lost on restart (users sign in again).
    """

    def __init__(self, ttl_seconds: int, *, max_sessions: int = MAX_SESSIONS,
                 clock: Callable[[], float] = time.time) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions
        self.clock = clock
        self._sessions: OrderedDict[str, float] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _key(session_id: str) -> str:
        return hashlib.sha256(session_id.encode("utf-8", "surrogatepass")).hexdigest()

    def create(self) -> tuple[str, dt.datetime]:
        session_id = secrets.token_urlsafe(32)
        now = self.clock()
        expires = now + self.ttl_seconds
        with self._lock:
            for key in [k for k, exp in self._sessions.items() if exp <= now]:
                del self._sessions[key]
            while len(self._sessions) >= self.max_sessions:
                self._sessions.popitem(last=False)  # drop the oldest
            self._sessions[self._key(session_id)] = expires
        return session_id, dt.datetime.fromtimestamp(expires, tz=dt.timezone.utc)

    def expires_at(self, session_id: str | None) -> dt.datetime | None:
        """Expiry of a live session, or None if unknown or expired (expired ones are dropped)."""
        if not session_id or len(session_id) > 256:
            return None
        key = self._key(session_id)
        with self._lock:
            expires = self._sessions.get(key)
            if expires is None:
                return None
            if expires <= self.clock():
                del self._sessions[key]
                return None
        return dt.datetime.fromtimestamp(expires, tz=dt.timezone.utc)

    def delete(self, session_id: str | None) -> None:
        if session_id:
            with self._lock:
                self._sessions.pop(self._key(session_id), None)

    def __len__(self) -> int:
        return len(self._sessions)


class AuthState:
    """Everything the middleware and the session routes share."""

    def __init__(self, token: str, *, session_ttl_seconds: int = 8 * 3600, cookie_secure: bool = True) -> None:
        self._expected_header = f"Bearer {token}".encode()
        self._token = token.encode()
        self.limiter = RateLimiter()
        self.sessions = SessionStore(session_ttl_seconds)
        self.cookie_secure = cookie_secure
        self.cookie_name = cookie_name(cookie_secure)

    def bearer_ok(self, header: bytes) -> bool:
        return hmac.compare_digest(header, self._expected_header)

    def token_ok(self, token: str) -> bool:
        return hmac.compare_digest(token.encode("utf-8", "surrogatepass"), self._token)


class BodyTooLarge(Exception):
    """Raised from ``receive`` when the streamed body passes the cap."""


def _peer(scope: Scope) -> str:
    client = scope.get("client") or ("unknown", 0)
    return str(client[0])[:128]


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, *, auth: AuthState, max_body_bytes: int,
                 is_ui_path: Callable[[str], bool] | None = None) -> None:
        self.app = app
        self.auth = auth
        self.max_body_bytes = max_body_bytes
        self.is_ui_path = is_ui_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        raw_headers: list[tuple[bytes, bytes]] = list(scope.get("headers") or [])
        headers = dict(raw_headers)
        path, method = scope["path"], scope["method"]

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                current = list(message.get("headers") or [])
                extra = list(_HARDENING_HEADERS)
                if not any(k.lower() == b"content-security-policy" for k, _ in current):
                    extra.append((b"content-security-policy", API_CSP.encode()))
                message["headers"] = current + extra
            await send(message)

        async def reject(status: int, detail: str, extra: dict[str, str] | None = None) -> None:
            await JSONResponse({"detail": detail}, status_code=status, headers=extra)(scope, receive, secure_send)

        csrf_ok = headers.get(CSRF_HEADER.lower().encode()) == b"1"

        if method in ("GET", "HEAD") and (
                path == "/healthz" or (self.is_ui_path is not None and self.is_ui_path(path))):
            await self.app(scope, receive, secure_send)
            return

        if path == SESSION_PATH and method in ("GET", "POST", "DELETE"):
            # The route reads the cookie (GET, DELETE) or checks the token (POST) itself.
            if method != "GET" and not csrf_ok:
                await reject(403, f"Missing {CSRF_HEADER} header")
                return
            if method == "POST" and self.auth.limiter.blocked(_peer(scope)):
                await reject(429, "Too many authentication attempts", {"Retry-After": "60"})
                return
            cap = SESSION_BODY_MAX_BYTES if method == "POST" else self.max_body_bytes
            await self._capped(scope, receive, secure_send, reject, headers, cap)
            return

        authorization = headers.get(b"authorization")
        if authorization is not None:
            ok, via = self.auth.bearer_ok(authorization), "bearer"
        else:
            sid = read_cookie(raw_headers, self.auth.cookie_name)
            ok, via = self.auth.sessions.expires_at(sid) is not None, "cookie"
        if not ok:
            if not self.auth.limiter.register_failure(_peer(scope)):
                await reject(429, "Too many authentication attempts", {"Retry-After": "60"})
                return
            await reject(401, "Invalid or missing bearer token", {"WWW-Authenticate": "Bearer"})
            return
        if via == "cookie" and method not in SAFE_METHODS and not csrf_ok:
            await reject(403, f"Missing {CSRF_HEADER} header")
            return
        scope.setdefault("state", {})["auth_via"] = via
        await self._capped(scope, receive, secure_send, reject, headers, self.max_body_bytes)

    async def _capped(self, scope: Scope, receive: Receive, send: Send,
                      reject: Callable[..., Awaitable[None]], headers: dict[bytes, bytes], cap: int) -> None:
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            await reject(400, "Invalid Content-Length")
            return
        if declared < 0 or declared > cap:
            await reject(413, "Request body exceeds the size limit")
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > cap:
                    raise BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except BodyTooLarge:
            await reject(413, "Request body exceeds the size limit")
