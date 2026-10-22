"""Pure ASGI middleware: body limit, security headers, no content in validation errors."""

import json

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cafe_norte.errors import MESSAGES

MAX_BODY_BYTES = 64 * 1024

# The page is Vite's same-origin build with no inline code; Daily is the only third party.
# daily-js fetches its call machine from c.daily.co and runs it with Function(): without
# 'unsafe-eval' no browser joins a room. Inline scripts stay blocked.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' 'unsafe-eval'",
        "connect-src 'self' https://*.daily.co wss://*.daily.co",
        "media-src 'self' blob:",
        "worker-src 'self' blob:",
        "img-src 'self' data:",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


class _BodyTooLarge(Exception):
    pass


class HttpBoundary:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        started = False
        overflowed = False

        async def guarded_send(message: Message) -> None:
            nonlocal started
            if overflowed:
                # Whatever the framework made of the aborted read (it may turn it into a 400),
                # the caller is told the truth, once; the app's own messages are dropped.
                if not started:
                    started = True
                    await _send_too_large(send)
                return
            if message["type"] == "http.response.start":
                started = True
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
            await send(message)

        declared = Headers(scope=scope).get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            await _send_too_large(send)
            return

        received = 0

        async def counted_receive() -> Message:
            nonlocal received, overflowed
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > MAX_BODY_BYTES:
                    overflowed = True
                    raise _BodyTooLarge
            return message

        try:
            await self._app(scope, counted_receive, guarded_send)
        except _BodyTooLarge:
            if not started:
                await _send_too_large(send)


async def _send_too_large(send: Send) -> None:
    body = json.dumps(
        {"code": "limit_exceeded", "message": MESSAGES["es"]["limit_exceeded"]}
    ).encode()
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode()),
        *((k.lower().encode(), v.encode()) for k, v in SECURITY_HEADERS.items()),
    ]
    await send({"type": "http.response.start", "status": 413, "headers": headers})
    await send({"type": "http.response.body", "body": body})
