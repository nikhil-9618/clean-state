"""HTTP hardening middleware: security headers, body size gate, client IP.

Headers are set on every response (API JSON, downloads and errors alike) unless
the endpoint already provided a stricter value.
"""

from __future__ import annotations

import json
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import Settings

CSP_API = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), magnetometer=(), "
    "microphone=(), payment=(), usb=(), interest-cohort=()"
)


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("Referrer-Policy", "no-referrer")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Content-Security-Policy", CSP_API)
                headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
                headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
                headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
                headers.setdefault("X-Permitted-Cross-Domain-Policies", "none")
                headers.setdefault("Cache-Control", "no-store")
                if self.settings.enable_hsts:
                    headers.setdefault(
                        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)


class BodySizeMiddleware:
    """Reject oversized requests early based on the declared Content-Length.

    Requests without Content-Length (chunked uploads) are still bounded while
    streaming in the upload handler, so the cap cannot be bypassed.
    """

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.limit = settings.max_request_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.decode("latin-1").lower(): value for key, value in scope.get("headers", [])}
        raw_length = headers.get("content-length")
        if raw_length:
            try:
                declared = int(raw_length)
            except ValueError:
                await self._reject(scope, receive, send, "invalid Content-Length header.")
                return
            if declared > self.limit:
                await self._reject(scope, receive, send, "The request body is too large.")
                return
        await self.app(scope, receive, send)

    async def _reject(self, scope: Scope, receive: Receive, send: Send, reason: str) -> None:
        payload = json.dumps(
            {
                "error": {
                    "code": "payload_too_large",
                    "message": "The upload exceeds the maximum accepted request size.",
                },
                "detail": reason if reason else None,
            }
        ).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
            (b"x-content-type-options", b"nosniff"),
            (b"referrer-policy", b"no-referrer"),
            (b"cache-control", b"no-store"),
        ]
        await send({"type": "http.response.start", "status": 413, "headers": headers})
        await send({"type": "http.response.body", "body": payload})


class RequestIdMiddleware:
    """Attach an opaque request id for troubleshooting (never used for tracking)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = uuid.uuid4().hex[:16]
        scope.setdefault("state", {})
        scope["state"]["request_id"] = request_id

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).setdefault("X-Request-Id", request_id)
            await send(message)

        await self.app(scope, receive, send_wrapper)
