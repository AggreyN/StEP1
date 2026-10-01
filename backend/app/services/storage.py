"""Resume storage — local filesystem in dev, S3 in prod.

Selected by STORAGE_BACKEND. One interface either way, so nothing upstream
knows which one is live:

    key = new_key(user_id)
    url, headers = presign_put(key, "application/pdf", size)   # browser uploads here
    size(key); head(key, 5); read(key, most); delete(key)

In S3 mode the browser PUTs straight to a short-lived presigned URL and the
API never proxies the bytes. In local mode the "presigned URL" points back at
this API's own PUT /profile/resume/local/{key}, so the identical upload flow
is exercisable with no AWS account.

Resumes are PII, and an upload is the one place a stranger hands us a file:

  * The key is made here, from the user's id and a random UUID. Nothing the
    client sent is in it: not the filename, not the extension. The name of
    the student's file is kept in the database, to show back to them.
  * A presigned PUT is signed for one content type and one exact length, so
    the URL cannot be used to store a different kind or size of file.
  * Objects are private and encrypted at rest. Nothing here can make a
    public URL, and no route serves a resume back through the API.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

from app import config

# resumes/<user id>/<uuid>.pdf — everything this service issues.
_KEY = re.compile(r"^resumes/(\d+)/[0-9a-f]{32}\.pdf$")
# resumes/<user id>/<12 hex>-<sanitized filename> — issued before keys
# stopped carrying the filename. Still recognised, so that a resume stored
# then can be read and, when it is replaced or its owner leaves, deleted.
# Never issued again, and never accepted for a new upload.
_LEGACY_KEY = re.compile(r"^resumes/(\d+)/[0-9a-f]{12}-[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


class StorageError(Exception):
    """The key is malformed, points outside the storage root, or the object
    is not what it was when it was measured."""


def new_key(user_id: int) -> str:
    """The key for a new upload. 122 random bits: not guessable, and not
    derived from anything a client controls."""
    return f"resumes/{int(user_id)}/{uuid.uuid4().hex}.pdf"


def owner_of(key: str) -> int | None:
    """The user id a key is namespaced under, or None if it is not a key."""
    if not isinstance(key, str) or ".." in key:
        return None
    match = _KEY.match(key) or _LEGACY_KEY.match(key)
    return int(match.group(1)) if match else None


def owns(user_id: int, key: str) -> bool:
    return owner_of(key) == user_id


def _check(key: str) -> str:
    if owner_of(key) is None:
        raise StorageError("Malformed storage key.")
    return key


def _local_path(key: str) -> Path:
    root = Path(config.UPLOAD_DIR).resolve()
    target = (root / _check(key)).resolve()
    if root not in target.parents:
        raise StorageError("Refusing to touch a path outside UPLOAD_DIR.")
    return target


def _s3():
    import boto3
    from botocore.config import Config

    # SigV4 explicitly. Under the older scheme, which boto3 can still choose
    # for S3, the content type and length are not part of what is signed, and
    # pinning them would be decoration.
    return boto3.client(
        "s3",
        region_name=config.AWS_REGION,
        config=Config(signature_version="s3v4"),
        # Unset in production. Set for a stand-in under test, or for another
        # S3-compatible store.
        endpoint_url=config.S3_ENDPOINT_URL or None,
    )


def _sse() -> tuple[dict, dict]:
    """Encryption at rest, as (parameters to sign, headers the client sends).
    Always requested, never left to the bucket's default: a bucket can be
    recreated without one."""
    if config.KMS_KEY_ID:
        return (
            {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": config.KMS_KEY_ID},
            {
                "x-amz-server-side-encryption": "aws:kms",
                "x-amz-server-side-encryption-aws-kms-key-id": config.KMS_KEY_ID,
            },
        )
    return (
        {"ServerSideEncryption": "AES256"},
        {"x-amz-server-side-encryption": "AES256"},
    )


def presign_put(key: str, content_type: str, size: int) -> tuple[str, dict[str, str]]:
    """Where the browser should PUT the file, and the headers it must send.

    The URL is good for exactly this key, this content type and this many
    bytes, for PRESIGN_EXPIRY_SECONDS. A request that differs in any of them
    fails the signature check at S3, or the same checks in the local route.

    A browser sets Content-Length itself, from the file, and will not let a
    script override it. It is returned here anyway: it is what the client
    must send, and clients that are not browsers need telling.
    """
    _check(key)
    headers = {"Content-Type": content_type, "Content-Length": str(int(size))}
    if config.STORAGE_BACKEND == "s3":
        sign, send = _sse()
        url = _s3().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": config.S3_BUCKET,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": int(size),
                **sign,
            },
            ExpiresIn=config.PRESIGN_EXPIRY_SECONDS,
            HttpMethod="PUT",
        )
        return url, headers | send
    return f"{config.PUBLIC_API_BASE}/profile/resume/local/{key}", headers


def write_local(key: str, data: bytes) -> None:
    """Local backend only: the body of PUT /profile/resume/local/{key}."""
    path = _local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Owner-only. The default would let any account on the machine read it.
    path.parent.chmod(0o700)
    path.write_bytes(data)
    path.chmod(0o600)


def size(key: str) -> int | None:
    """Object size in bytes as stored, or None if it doesn't exist."""
    if config.STORAGE_BACKEND == "s3":
        from botocore.exceptions import ClientError

        try:
            found = _s3().head_object(Bucket=config.S3_BUCKET, Key=_check(key))
        except ClientError:
            return None
        return int(found["ContentLength"])
    path = _local_path(key)
    return path.stat().st_size if path.is_file() else None


def exists(key: str) -> bool:
    return size(key) is not None


def head(key: str, count: int) -> bytes:
    """The first `count` bytes, without fetching the rest: enough to tell
    what a file is before deciding whether to read it."""
    if config.STORAGE_BACKEND == "s3":
        obj = _s3().get_object(
            Bucket=config.S3_BUCKET, Key=_check(key), Range=f"bytes=0-{count - 1}"
        )
        return obj["Body"].read(count)
    with _local_path(key).open("rb") as f:
        return f.read(count)


def read(key: str, most: int) -> bytes:
    """The object, refusing to hold more than `most` bytes of it. The caller
    has checked the size; this is for the object that grew in between."""
    if config.STORAGE_BACKEND == "s3":
        body = _s3().get_object(Bucket=config.S3_BUCKET, Key=_check(key))["Body"]
        data = body.read(most + 1)
    else:
        with _local_path(key).open("rb") as f:
            data = f.read(most + 1)
    if len(data) > most:
        raise StorageError("The stored object is larger than allowed.")
    return data


def delete(key: str) -> bool:
    """Remove an object. True if it is gone, including if it was never there.
    Never raises: a failed delete must not fail the request that asked for
    it. But the caller is told, because a resume that should be gone and is
    not has to be logged."""
    try:
        if config.STORAGE_BACKEND == "s3":
            _s3().delete_object(Bucket=config.S3_BUCKET, Key=_check(key))
        else:
            _local_path(key).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        return False
    return True


def attachment(filename: str) -> str:
    """A Content-Disposition value that makes a browser save the file under
    this name. The plain `filename=` is ASCII with quotes and backslashes
    removed, for old clients; `filename*=` carries the real name, encoded."""
    import unicodedata
    from urllib.parse import quote

    ascii_name = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode()
    ascii_name = "".join(c for c in ascii_name if 32 <= ord(c) < 127 and c not in '"\\') or "file"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def presign_get(key: str, filename: str) -> str:
    """S3 only: a short-lived URL that downloads the object as an attachment
    named `filename`. Good for PRESIGN_EXPIRY_SECONDS."""
    return _s3().generate_presigned_url(
        "get_object",
        Params={
            "Bucket": config.S3_BUCKET,
            "Key": _check(key),
            "ResponseContentDisposition": attachment(filename),
            "ResponseContentType": "application/pdf",
        },
        ExpiresIn=config.PRESIGN_EXPIRY_SECONDS,
        HttpMethod="GET",
    )


def local_path(key: str) -> Path:
    """Local backend only: where the object is on disk."""
    return _local_path(key)
