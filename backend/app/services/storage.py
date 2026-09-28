"""Resume storage — local filesystem in dev, S3 in prod.

Selected by STORAGE_BACKEND. One interface either way, so nothing upstream
knows which one is live:

    key = resume_key(user_id, "resume.pdf")
    url, headers = presign_put(key, "application/pdf")   # browser uploads here
    exists(key); size(key); read(key); delete(key)

In S3 mode the browser PUTs straight to a short-lived presigned URL and the
API never proxies the bytes. In local mode the "presigned URL" points back at
this API's own PUT /profile/resume/local/{key}, so the identical upload flow
is exercisable with no AWS account.

Resumes are PII: keys are namespaced per user, ownership is checked on every
operation that takes a key from a client, and objects are never public.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

from app import config

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")
# resumes/<user id>/<12 hex>-<sanitized filename>. Anything else is not a key
# this service issued, and is refused before it gets near a filesystem path.
_KEY = re.compile(r"^resumes/(\d+)/[0-9a-f]{12}-[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


class StorageError(Exception):
    """The key is malformed or points outside the storage root."""


def safe_name(filename: str) -> str:
    name = os.path.basename((filename or "").replace("\\", "/"))
    name = _SAFE.sub("_", name).strip("._-") or "resume.pdf"
    return name[:200]


def resume_key(user_id: int, filename: str) -> str:
    """A collision-proof key that keeps the original name readable."""
    return f"resumes/{user_id}/{uuid.uuid4().hex[:12]}-{safe_name(filename)}"


def owns(user_id: int, key: str) -> bool:
    match = _KEY.match(key or "")
    return bool(match) and int(match.group(1)) == user_id


def _check(key: str) -> str:
    if not _KEY.match(key or "") or ".." in key:
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

    return boto3.client("s3", region_name=config.AWS_REGION)


def _sse_params() -> dict:
    # The bucket enforces default encryption (SSE-S3). Ask for SSE-KMS only
    # when a CMK is configured — requesting it unconditionally needs KMS
    # grants the service role doesn't otherwise carry.
    if config.KMS_KEY_ID:
        return {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": config.KMS_KEY_ID}
    return {}


def presign_put(key: str, content_type: str) -> tuple[str, dict[str, str]]:
    """Where the browser should PUT the file, and the headers it must send."""
    _check(key)
    headers = {"Content-Type": content_type}
    if config.STORAGE_BACKEND == "s3":
        params = {
            "Bucket": config.S3_BUCKET,
            "Key": key,
            "ContentType": content_type,
            **_sse_params(),
        }
        url = _s3().generate_presigned_url(
            "put_object", Params=params, ExpiresIn=config.PRESIGN_EXPIRY_SECONDS
        )
        if config.KMS_KEY_ID:
            # Signed headers must be replayed verbatim by the browser.
            headers["x-amz-server-side-encryption"] = "aws:kms"
            headers["x-amz-server-side-encryption-aws-kms-key-id"] = config.KMS_KEY_ID
        return url, headers
    return f"{config.PUBLIC_API_BASE}/profile/resume/local/{key}", headers


def write_local(key: str, data: bytes) -> None:
    """Local backend only: the body of PUT /profile/resume/local/{key}."""
    path = _local_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def size(key: str) -> int | None:
    """Object size in bytes, or None if it doesn't exist."""
    if config.STORAGE_BACKEND == "s3":
        from botocore.exceptions import ClientError

        try:
            head = _s3().head_object(Bucket=config.S3_BUCKET, Key=_check(key))
        except ClientError:
            return None
        return int(head["ContentLength"])
    path = _local_path(key)
    return path.stat().st_size if path.is_file() else None


def exists(key: str) -> bool:
    return size(key) is not None


def read(key: str) -> bytes:
    if config.STORAGE_BACKEND == "s3":
        obj = _s3().get_object(Bucket=config.S3_BUCKET, Key=_check(key))
        return obj["Body"].read()
    return _local_path(key).read_bytes()


def delete(key: str) -> None:
    """Best-effort: a replaced resume must not linger, but failing to delete
    the old object is not a reason to fail the new upload."""
    try:
        if config.STORAGE_BACKEND == "s3":
            _s3().delete_object(Bucket=config.S3_BUCKET, Key=_check(key))
        else:
            _local_path(key).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
