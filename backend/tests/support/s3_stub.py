"""A local stand-in for Amazon S3 that checks signatures.

moto stores objects and answers the S3 API, which is enough to test that
the right calls are made. It does not check a presigned URL's signature: it
accepts any upload to any URL. The whole point of a presigned PUT is what it
refuses, so moto alone cannot test it.

This puts a verifier in front of moto that does what S3 does with a presigned
URL. It rebuilds the request that was signed from the request that actually
arrived (its method, path, query and the value of every header named in
X-Amz-SignedHeaders), signs that with the same secret, and compares. A request
that differs in any signed respect produces a different signature and is
refused with 403, as S3 refuses it.

The signing here is written from the published Signature Version 4
algorithm, not borrowed from the SDK that made the URL. If either were wrong,
a correctly signed upload would be refused, and the tests that expect it to
succeed would fail.
"""

from __future__ import annotations

import hashlib
import hmac
import socket
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, quote

from moto.server import DomainDispatcherApplication, create_backend_app
from werkzeug.serving import make_server

ACCESS_KEY = "AKIAIOSFODNN7EXAMPLE"
SECRET_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def _hmac(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode(), hashlib.sha256).digest()


def expected_signature(method: str, path: str, query: list[tuple[str, str]], headers) -> str:
    """The signature S3 would compute for this request, as it arrived."""
    params = dict(query)
    signed_headers = params["X-Amz-SignedHeaders"].split(";")
    _, date, region, service, _ = params["X-Amz-Credential"].split("/")

    canonical_query = "&".join(
        f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}"
        for k, v in sorted(query)
        if k != "X-Amz-Signature"
    )
    canonical_headers = "".join(
        f"{name}:{' '.join((headers.get(name) or '').split())}\n" for name in signed_headers
    )
    canonical_request = "\n".join(
        [
            method,
            quote(path, safe="/-_.~"),
            canonical_query,
            canonical_headers,
            ";".join(signed_headers),
            "UNSIGNED-PAYLOAD",
        ]
    )
    scope = f"{date}/{region}/{service}/aws4_request"
    to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            params["X-Amz-Date"],
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    key = _hmac(_hmac(_hmac(_hmac(f"AWS4{SECRET_KEY}".encode(), date), region), service),
                "aws4_request")  # fmt: skip
    return hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()


class CheckPresignedRequests:
    """WSGI middleware: refuse a presigned request S3 would refuse."""

    def __init__(self, app):
        self.app = app
        self.refused: list[str] = []
        self.accepted = 0

    def _refuse(self, start_response, code: str, message: str):
        self.refused.append(code)
        body = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n<Error><Code>{code}</Code>'
            f"<Message>{message}</Message></Error>"
        ).encode()
        start_response(
            "403 Forbidden",
            [("Content-Type", "application/xml"), ("Content-Length", str(len(body)))],
        )
        return [body]

    def __call__(self, environ, start_response):
        query = parse_qsl(environ.get("QUERY_STRING", ""), keep_blank_values=True)
        params = dict(query)
        if "X-Amz-Signature" not in params:
            return self.app(environ, start_response)  # an SDK call, not a presigned URL

        headers = {
            "host": environ.get("HTTP_HOST", ""),
            "content-type": environ.get("CONTENT_TYPE", ""),
            "content-length": environ.get("CONTENT_LENGTH", ""),
        }
        for name, value in environ.items():
            if name.startswith("HTTP_"):
                headers[name[5:].replace("_", "-").lower()] = value

        signed_at = datetime.strptime(params["X-Amz-Date"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        if datetime.now(UTC) > signed_at + timedelta(seconds=int(params["X-Amz-Expires"])):
            return self._refuse(start_response, "AccessDenied", "Request has expired")

        for name in params["X-Amz-SignedHeaders"].split(";"):
            if not headers.get(name):
                return self._refuse(
                    start_response, "AccessDenied",
                    f"There were headers present in the request which were not signed: {name}",
                )  # fmt: skip

        expected = expected_signature(
            environ["REQUEST_METHOD"], environ.get("PATH_INFO", ""), query, headers
        )
        if not hmac.compare_digest(expected, params["X-Amz-Signature"]):
            return self._refuse(
                start_response, "SignatureDoesNotMatch",
                "The request signature we calculated does not match the signature you provided.",
            )  # fmt: skip

        # A sent body shorter than the Content-Length header promised would hang a
        # naive read-to-length here, since the client (having already closed its
        # side) never supplies the missing bytes. The WSGI server already refuses
        # to hand this application more bytes than Content-Length declared, and a
        # short actual body simply surfaces downstream as moto reading a truncated
        # object; either way nothing here needs to read the body itself.
        self.accepted += 1
        return self.app(environ, start_response)


class S3Stub:
    def __init__(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.checker = CheckPresignedRequests(DomainDispatcherApplication(create_backend_app))
        self.url = f"http://127.0.0.1:{self.port}"
        self._server = make_server("127.0.0.1", self.port, self.checker, threaded=True)
        self._thread = threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True
        )

    def start(self) -> S3Stub:
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
