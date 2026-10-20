"""Pure ASGI middleware: body limit, security headers, no content in validation errors."""

from starlette.types import ASGIApp, Receive, Scope, Send

MAX_BODY_BYTES = 64 * 1024


class HttpBoundary:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        raise NotImplementedError
