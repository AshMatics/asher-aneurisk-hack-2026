"""Authentication before the body is read, a body size cap and response hardening.

The same pattern as the segmentation worker (``slicepoint/segmentation/slicepoint_model/
security.py``): a pure ASGI middleware checks ``Authorization: Bearer <token>`` with
:func:`hmac.compare_digest` before FastAPI parses anything, so an unauthenticated client
never gets a request body parsed or validated. ``GET /healthz`` is the only open route.
"""

from __future__ import annotations

import hmac
import threading
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from starlette.responses import JSONResponse

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

BAD_AUTH_PER_MINUTE = 10
"""Failed authentication attempts allowed per client address per minute."""

_HARDENING_HEADERS = [
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
]


class BodyTooLarge(Exception):
    """Raised from ``receive`` when the streamed body passes the cap."""


class SecurityMiddleware:
    def __init__(self, app: ASGIApp, *, token: str, max_body_bytes: int) -> None:
        self.app = app
        self._expected = f"Bearer {token}".encode()
        self.max_body_bytes = max_body_bytes
        self._attempts: defaultdict[bytes, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _bad_auth_allowed(self, peer: bytes) -> bool:
        now = time.monotonic()
        with self._lock:
            queue = self._attempts[peer]
            while queue and queue[0] <= now - 60:
                queue.popleft()
            if len(queue) >= BAD_AUTH_PER_MINUTE:
                return False
            queue.append(now)
            if len(self._attempts) > 2048:  # no unbounded remote-address map
                self._attempts = defaultdict(deque, {peer: queue})
            return True

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])

        async def secure_send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                message["headers"] = list(message["headers"]) + _HARDENING_HEADERS
            await send(message)

        async def reject(status: int, detail: str, extra: dict[str, str] | None = None) -> None:
            await JSONResponse({"detail": detail}, status_code=status, headers=extra)(scope, receive, secure_send)

        if scope["path"] == "/healthz" and scope["method"] in ("GET", "HEAD"):
            await self.app(scope, receive, secure_send)
            return
        if not hmac.compare_digest(headers.get(b"authorization", b""), self._expected):
            client = scope.get("client") or ("unknown", 0)
            if not self._bad_auth_allowed(str(client[0]).encode()[:128]):
                await reject(429, "Too many authentication attempts", {"Retry-After": "60"})
                return
            await reject(401, "Invalid or missing bearer token", {"WWW-Authenticate": "Bearer"})
            return
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            await reject(400, "Invalid Content-Length")
            return
        if declared < 0 or declared > self.max_body_bytes:
            await reject(413, "Request body exceeds the size limit")
            return
        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    raise BodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, secure_send)
        except BodyTooLarge:
            await reject(413, "Request body exceeds the size limit")
