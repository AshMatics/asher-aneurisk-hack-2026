"""Authenticate before multipart parsing; bound uploads and request frequency."""
import asyncio
from collections import defaultdict, deque
import hmac
import os
import threading
import time

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse


def valid_token(header):
    token = os.environ.get('SLICEPOINT_API_TOKEN', '')
    if len(token) < 32:
        return None
    return hmac.compare_digest(header, f'Bearer {token}'.encode())


class SecurityMiddleware:
    def __init__(self, app):
        self.app = app
        self.attempts = defaultdict(deque)
        self.limit_lock = threading.Lock()
        self.inflight = threading.BoundedSemaphore(2)

    def rate_allowed(self, key, limit):
        now = time.monotonic()
        with self.limit_lock:
            queue = self.attempts[key]
            while queue and queue[0] <= now - 60:
                queue.popleft()
            if len(queue) >= limit:
                return False
            queue.append(now)
            # Cap the number of tracked sources; no unbounded remote-IP map.
            if len(self.attempts) > 2048:
                self.attempts = defaultdict(deque, {key: queue})
            return True

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))

        async def secure_send(message):
            if message['type'] == 'http.response.start':
                message.setdefault('headers', []).extend([
                    (b'cache-control', b'no-store'),
                    (b'x-content-type-options', b'nosniff'),
                    (b'x-frame-options', b'DENY'),
                    (b'referrer-policy', b'no-referrer'),
                ])
            await send(message)

        async def reject(status, detail, extra=None):
            await JSONResponse({'detail': detail}, status_code=status, headers=extra or {})(scope, receive, secure_send)

        path = scope['path']
        if path == '/healthz' and scope['method'] == 'GET':
            return await self.app(scope, receive, secure_send)
        if path not in ('/v1/compare', '/v1/segment'):
            return await reject(404, 'Not found')
        if scope['method'] != 'POST':
            return await reject(405, 'POST required')
        allowed = valid_token(headers.get(b'authorization', b''))
        if allowed is None:
            return await reject(503, 'Service authentication is not configured')
        if not allowed:
            # Cloudflare overwrites this header; Uvicorn listens only on loopback.
            peer = headers.get(b'cf-connecting-ip', str(scope.get('client', ('unknown',))[0]).encode())
            if not self.rate_allowed(('bad_auth', peer[:128]), 10):
                return await reject(429, 'Too many authentication attempts', {'Retry-After': '60'})
            return await reject(401, 'Invalid bearer token')
        if not self.rate_allowed(('authenticated',), int(os.environ.get('MAX_REQUESTS_PER_MINUTE', '30'))):
            return await reject(429, 'Request limit reached; retry later', {'Retry-After': '60'})
        max_bytes = (int(os.environ.get('MAX_UPLOAD_MB', '64')) + 1) * 1024 * 1024
        try:
            declared = int(headers.get(b'content-length', b'0'))
        except ValueError:
            return await reject(400, 'Invalid Content-Length')
        if declared < 0 or declared > max_bytes:
            return await reject(413, 'Request exceeds upload limit')
        if not self.inflight.acquire(blocking=False):
            return await reject(503, 'Service is busy; retry later', {'Retry-After': '30'})
        received = 0

        async def limited_receive():
            nonlocal received
            try:
                message = await asyncio.wait_for(receive(), timeout=30)
            except asyncio.TimeoutError:
                raise HTTPException(408, 'Upload timed out')
            if message['type'] == 'http.request':
                received += len(message.get('body', b''))
                if received > max_bytes:
                    raise HTTPException(413, 'Request exceeds upload limit')
            return message
        try:
            await self.app(scope, limited_receive, secure_send)
        finally:
            self.inflight.release()
