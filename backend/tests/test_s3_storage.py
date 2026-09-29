"""STORAGE_BACKEND=s3, tested against a local stand-in for S3.

Never run against a real bucket. Instead moto's S3 backend runs as a real
HTTP server, with tests/support/s3_stub.CheckPresignedRequests in front of
it: a from-scratch implementation of SigV4 that checks a presigned request's
signature the way S3 does. Plain moto accepts any PUT to any URL regardless
of its signature, which would make every "the presigned URL pins X" test
below pass whether or not app/services/storage.py's pinning worked at all.

What this does not prove: that the added checker agrees with real S3 down to
the byte. It is written from the published algorithm and cross-checked here
against the signatures boto3 itself produces (a correctly signed upload has
to succeed, in every test below, or the checker is wrong) but it has never
run against an AWS account. That would need one and is out of scope here.

Everything else — commit reading real bytes back, the magic-byte check,
deleting the previous resume on replace, deleting objects on account
deletion, a slot nobody ever uploaded to — runs through the same route code
as the local-backend tests in test_resume.py; this file exists to run it
with config.STORAGE_BACKEND == "s3" instead, so that code path is exercised
too, not just the local-file one.
"""

from __future__ import annotations

import os
import re
import urllib.error
import urllib.request

import pytest
from sqlalchemy import select

from app import config
from app.models import Profile, ResumeUpload
from app.services import storage
from tests.conftest import make_pdf, register
from tests.support.s3_stub import ACCESS_KEY, SECRET_KEY, S3Stub

KEY = re.compile(r"^resumes/(\d+)/[0-9a-f]{32}\.pdf$")
BUCKET = "step1-resumes-test"


@pytest.fixture(scope="module")
def stub():
    os.environ.setdefault("AWS_ACCESS_KEY_ID", ACCESS_KEY)
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", SECRET_KEY)
    os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")
    server = S3Stub().start()
    import boto3
    from botocore.config import Config

    boto3.client(
        "s3",
        region_name="us-east-1",
        endpoint_url=server.url,
        config=Config(signature_version="s3v4"),
    ).create_bucket(Bucket=BUCKET)
    yield server
    server.stop()


@pytest.fixture()
def s3(monkeypatch, stub):
    """Every test in this file runs with STORAGE_BACKEND=s3, against the
    stand-in server, restored to the local backend when the test ends."""
    monkeypatch.setattr(config, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(config, "S3_BUCKET", BUCKET)
    monkeypatch.setattr(config, "S3_ENDPOINT_URL", stub.url)
    monkeypatch.setattr(config, "AWS_REGION", "us-east-1")
    stub.checker.refused.clear()
    stub.checker.accepted = 0
    return stub


def put_s3(target: dict, data: bytes, **extra_headers) -> int:
    """PUT to a presigned URL the way a browser would, plus whatever the
    test wants to override or drop (a None value drops the header)."""
    headers = {**target["headers"], **extra_headers}
    headers = {k: v for k, v in headers.items() if v is not None}
    req = urllib.request.Request(target["upload_url"], data=data, method="PUT", headers=headers)
    try:
        return urllib.request.urlopen(req, timeout=5).status
    except urllib.error.HTTPError as e:
        return e.code


def presign(client, headers, size, filename="resume.pdf") -> dict:
    r = client.post(
        "/profile/resume/presign",
        json={"filename": filename, "content_type": "application/pdf", "size": size},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


def commit(client, headers, key, filename="resume.pdf"):
    return client.post(
        "/profile/resume/commit", json={"key": key, "filename": filename}, headers=headers
    )


def upload(client, headers, data: bytes | None = None, filename: str = "resume.pdf"):
    """presign -> PUT straight to the stand-in -> commit, as a browser in S3
    mode would do it (no proxying through the API for the PUT itself)."""
    data = make_pdf() if data is None else data
    target = presign(client, headers, len(data), filename)
    status = put_s3(target, data)
    assert status == 200, status
    return target, commit(client, headers, target["key"], filename)


# --------------------------------------------------------------------------- #
# The presigned URL itself
# --------------------------------------------------------------------------- #


def test_presign_points_at_s3_and_is_server_generated(client, auth, s3):
    data = make_pdf()
    target = presign(client, auth, len(data))
    assert target["upload_url"].startswith(s3.url)
    # resumes/<user id>/<32 random hex>.pdf: nothing the client sent (a
    # filename, an extension it chose) reaches the key.
    assert KEY.match(target["key"])
    assert target["headers"]["Content-Type"] == "application/pdf"
    assert target["headers"]["Content-Length"] == str(len(data))
    assert target["headers"]["x-amz-server-side-encryption"] == "AES256"


def test_correctly_signed_upload_is_accepted(client, auth, s3):
    """The baseline every refusal below is measured against: a request that
    matches the presign in every signed respect must succeed, or the checker
    standing in for S3 is wrong, not the code under test."""
    data = make_pdf()
    target = presign(client, auth, len(data))
    assert put_s3(target, data) == 200
    assert storage.size(target["key"]) == len(data)


def test_wrong_content_type_is_refused(client, auth, s3):
    data = make_pdf()
    target = presign(client, auth, len(data))
    status = put_s3(target, data, **{"Content-Type": "text/html"})
    assert status == 403
    assert stub_refusal(s3) == "SignatureDoesNotMatch"
    assert storage.size(target["key"]) is None


def test_declaring_and_sending_a_different_length_is_refused(client, auth, s3):
    """An attacker who wants a smaller (or larger) object under this key has
    to lie about the length both in the signed request and on the wire; the
    signed Content-Length header no longer matches what the URL was signed
    for, so the signature check fails before a single byte is stored."""
    data = make_pdf()
    target = presign(client, auth, len(data))
    shorter = data[:-1]
    status = put_s3(target, shorter, **{"Content-Length": str(len(shorter))})
    assert status == 403
    assert stub_refusal(s3) == "SignatureDoesNotMatch"
    assert storage.size(target["key"]) is None


def test_sending_extra_bytes_past_the_signed_length_does_not_grow_the_object(client, auth, s3):
    """A client that sends more bytes than Content-Length declared (while
    leaving the declared, signed value alone) is not refused by the
    signature check — the header is exactly what was signed — but HTTP
    framing itself means only the declared number of bytes becomes the
    object's body. The trailing bytes go nowhere. Either way, nobody can
    smuggle a bigger file under a presigned size."""
    data = make_pdf()
    target = presign(client, auth, len(data))
    status = put_s3(target, data + b"\x00" * 512)
    assert status == 200
    assert storage.size(target["key"]) == len(data)


def test_missing_sse_header_is_refused(client, auth, s3):
    data = make_pdf()
    target = presign(client, auth, len(data))
    status = put_s3(target, data, **{"x-amz-server-side-encryption": None})
    assert status == 403
    assert storage.size(target["key"]) is None


def test_wrong_sse_value_is_refused(client, auth, s3):
    data = make_pdf()
    target = presign(client, auth, len(data))
    status = put_s3(target, data, **{"x-amz-server-side-encryption": "aws:kms"})
    assert status == 403
    assert stub_refusal(s3) == "SignatureDoesNotMatch"
    assert storage.size(target["key"]) is None


def test_a_presigned_url_cannot_be_redirected_to_a_different_key(client, auth, s3):
    data = make_pdf()
    target = presign(client, auth, len(data))
    other_key = target["key"].rsplit("/", 1)[0] + "/" + "0" * 32 + ".pdf"
    elsewhere = dict(target, upload_url=target["upload_url"].replace(target["key"], other_key))
    status = put_s3(elsewhere, data)
    assert status == 403
    assert storage.size(other_key) is None


def test_expired_or_extended_expiry_is_refused(client, auth, s3):
    data = make_pdf()
    target = presign(client, auth, len(data))
    longer = dict(target, upload_url=re.sub(r"Expires=\d+", "Expires=604800", target["upload_url"]))
    status = put_s3(longer, data)
    assert status == 403


def stub_refusal(s3) -> str | None:
    return s3.checker.refused[-1] if s3.checker.refused else None


# --------------------------------------------------------------------------- #
# The rest of the flow, run against the stand-in instead of the filesystem
# --------------------------------------------------------------------------- #


def test_full_upload_flow(client, s3):
    headers = register(client)
    data = make_pdf()
    target, r = upload(client, headers, data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["filename"] == "resume.pdf"
    assert body["skills"]
    assert storage.size(target["key"]) == len(data)


def test_head_and_size_read_from_s3(client, s3):
    headers = register(client, email="head@umd.edu")
    data = make_pdf()
    target, r = upload(client, headers, data)
    assert r.status_code == 200, r.text
    assert storage.head(target["key"], 5) == b"%PDF-"
    assert storage.size(target["key"]) == len(data)
    assert storage.read(target["key"], most=len(data)) == data


def test_non_pdf_bytes_are_refused_and_deleted(client, s3, db):
    headers = register(client, email="notpdf@umd.edu")
    # Big enough to clear RESUME_MIN_BYTES, so the size checks pass and the
    # magic-byte check is what actually catches this one.
    fake = b"not really a pdf, but the declared type and size are honest " + b"x" * 1200
    target = presign(client, headers, len(fake))
    assert put_s3(target, fake) == 200
    assert storage.size(target["key"]) == len(fake)

    r = commit(client, headers, target["key"])
    assert r.status_code == 400, r.text

    assert storage.size(target["key"]) is None
    db.expire_all()
    assert db.scalar(select(ResumeUpload).where(ResumeUpload.key == target["key"])) is None


def test_missing_object_is_handled_cleanly(client, s3):
    """A commit for a slot nobody ever PUT to: no object to look at, no
    crash, a plain refusal, and the slot survives so the same key can still
    be used if the browser retries the PUT."""
    headers = register(client, email="never-uploaded@umd.edu")
    data = make_pdf()
    target = presign(client, headers, len(data))

    r = commit(client, headers, target["key"])
    assert r.status_code == 400, r.text
    assert "Upload it first" in r.json()["detail"]

    # The slot was not discarded: the same key still works once it is used.
    assert put_s3(target, data) == 200
    r2 = commit(client, headers, target["key"])
    assert r2.status_code == 200, r2.text


def test_replacing_a_resume_deletes_the_previous_object(client, s3):
    headers = register(client, email="replace@umd.edu")
    first, r1 = upload(client, headers, make_pdf(extra="first"))
    assert r1.status_code == 200, r1.text
    assert storage.size(first["key"]) is not None

    second, r2 = upload(client, headers, make_pdf(extra="second"))
    assert r2.status_code == 200, r2.text

    assert storage.size(first["key"]) is None
    assert storage.size(second["key"]) is not None


def test_deleting_the_account_deletes_the_resume_object(client, s3, db):
    headers = register(client, email="verify-delete-s3@umd.edu", password="correct-horse")
    target, r = upload(client, headers)
    assert r.status_code == 200, r.text
    assert storage.size(target["key"]) is not None

    d = client.request("DELETE", "/me", json={"password": "correct-horse"}, headers=headers)
    assert d.status_code == 204, d.text

    assert storage.size(target["key"]) is None
    db.expire_all()
    assert db.scalar(select(Profile).where(Profile.resume_s3_key == target["key"])) is None
