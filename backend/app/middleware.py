"""ASGI middleware that applies to every request, whatever the route.

Pure ASGI rather than BaseHTTPMiddleware: no threadpool hop, no interference
with BackgroundTasks, and the body is never buffered on the way through.
"""

from __future__ import annotations

import json
import logging

from fastapi import HTTPException

from app import config, limits

log = logging.getLogger(__name__)

_TOO_LARGE = "That request is too large."
_BROKEN = "Something went wrong on our side. Please try again."


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key == name:
            return value.decode("latin-1")
    return None


def client_ip(scope) -> str:
    """The address of whoever is really making the request.

    With no trusted proxy that is the peer on the socket, and
    X-Forwarded-For is ignored: it is a header, and says what its sender
    likes. Behind trusted proxies it is the entry TRUSTED_PROXY_HOPS from the
    right of X-Forwarded-For, the one the outermost of our own proxies wrote.
    Entries to its left came with the request and are not believed.
    """
    peer = (scope.get("client") or ("unknown", 0))[0]
    if not config.TRUST_PROXY:
        return peer
    forwarded = [p.strip() for p in (_header(scope, b"x-forwarded-for") or "").split(",")]
    forwarded = [p for p in forwarded if p]
    hops = max(config.TRUSTED_PROXY_HOPS, 1)
    if len(forwarded) >= hops:
        return forwarded[-hops]
    # Fewer entries than proxies: the request did not come the way we think
    # requests come. Fall back to what cannot be forged.
    return peer


def is_https(scope) -> bool:
    if scope.get("scheme") == "https":
        return True
    if config.TRUST_PROXY:
        proto = (_header(scope, b"x-forwarded-proto") or "").split(",")[-1].strip().lower()
        return proto == "https"
    return False


class SecurityHeadersMiddleware:
    """The same few headers on every response, whatever produced it.

    This is a JSON API. Nothing it returns should ever be rendered as a page,
    framed, or have its type guessed, so the policy is the strictest there is:
    load nothing, from nowhere. If a response is ever wrongly treated as HTML,
    by a browser bug or a future mistake here, a script in it will not run.
    """

    API_CSP = "default-src 'none'; frame-ancestors 'none'"
    # The interactive docs are a page, and load Swagger UI from a CDN. Only
    # served outside production, and only these paths get the looser policy.
    DOCS_CSP = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "img-src 'self' data: https://fastapi.tiangolo.com; "
        "frame-ancestors 'none'"
    )
    DOCS_PATHS = ("/docs", "/docs/oauth2-redirect")
    HSTS = "max-age=31536000; includeSubDomains"

    def __init__(self, app, prod: bool = False):
        self.app = app
        self.prod = prod

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # The looser policy only where the docs are actually served. In
        # production those paths are 404s, and a 404 is API like any other.
        docs = not self.prod and scope["path"] in self.DOCS_PATHS
        policy = self.DOCS_CSP if docs else self.API_CSP
        wanted = {
            b"x-content-type-options": b"nosniff",
            b"referrer-policy": b"strict-origin-when-cross-origin",
            b"x-frame-options": b"DENY",
            b"content-security-policy": policy.encode(),
            # Responses here are one person's data. No cache, shared or
            # private, should keep a copy. A route that is safe to cache
            # says so itself, and its header wins.
            b"cache-control": b"no-store",
        }
        # Only over HTTPS: a browser ignores it over plain HTTP, and sending
        # it from a laptop's http://localhost would be a header that means
        # nothing. In production every request arrived over HTTPS, whatever
        # the last hop looked like.
        if self.prod or is_https(scope):
            wanted[b"strict-transport-security"] = self.HSTS.encode()

        async def with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {key.lower() for key, _ in headers}
                headers += [(k, v) for k, v in wanted.items() if k not in present]
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, with_headers)


class ErrorBoundaryMiddleware:
    """Turns an unhandled exception into an ordinary response, here, on the
    inside of every other middleware.

    Left alone, an exception travels out through all of them and is answered
    by the framework's outermost layer. That answer has no CORS headers, so a
    browser reports a network error instead of the message; no security
    headers; and no request id to find the traceback by. Answering here means
    a 500 is a response like any other.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def watched(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, watched)
        except Exception:
            # The traceback goes to the log, joined to the response by its
            # request id. Nothing about the failure goes to the client.
            log.exception(
                "unhandled error",
                extra={"request_id": scope.get("state", {}).get("request_id")},
            )
            if started:
                raise  # half a response is already on the wire
            await _respond(send, 500, _BROKEN)


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


async def _respond(send, status: int, detail: str, extra: tuple = ()) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                *extra,
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


async def _reject(send) -> None:
    # We have not read the body and will not, so the connection cannot be
    # reused for another request.
    await _respond(send, 413, _TOO_LARGE, ((b"connection", b"close"),))
