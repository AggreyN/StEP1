"""ASGI middleware that applies to every request, whatever the route.

Pure ASGI rather than BaseHTTPMiddleware: no threadpool hop, no interference
with BackgroundTasks, and the body is never buffered on the way through.
"""

from __future__ import annotations

import json

from fastapi import HTTPException

from app import limits

_TOO_LARGE = "That request is too large."


class BodyLimitMiddleware:
    """Refuse a request body over the limit, without reading it.

    Validation bounds what a body may *say*; this bounds how much of it we
    are willing to hear. Without it, a request for any JSON route can carry a
    gigabyte, and it is all in memory before a single field is checked.

    Routes under `exempt` police their own size: a resume upload is larger
    than any JSON body and has its own, stricter accounting.
    """

    def __init__(self, app, max_bytes: int = limits.JSON_BODY_MAX_BYTES, exempt: tuple = ()):
        self.app = app
        self.max_bytes = max_bytes
        self.exempt = exempt

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] in ("GET", "HEAD", "OPTIONS")
            or scope["path"].startswith(self.exempt)
        ):
            await self.app(scope, receive, send)
            return

        declared = next((v for k, v in scope.get("headers", []) if k == b"content-length"), None)
        if declared is not None and (not declared.isdigit() or int(declared) > self.max_bytes):
            await _reject(send)
            return

        # Content-Length can be absent (chunked) or a lie, so count what
        # actually arrives and stop listening at the limit.
        received = 0

        async def counted():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    # FastAPI re-raises an HTTPException met while reading a
                    # body, so this reaches the client as a normal error.
                    raise HTTPException(413, _TOO_LARGE)
            return message

        await self.app(scope, counted, send)


async def _reject(send) -> None:
    body = json.dumps({"detail": _TOO_LARGE}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                # We have not read the body and will not; the connection
                # cannot be reused for another request.
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
