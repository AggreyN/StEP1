"""The resume upload: presign -> PUT -> commit.

The one place a stranger hands the API a file. Every claim the client makes
about that file (its name, its type, its size) is either pinned in advance
and enforced, or ignored in favour of what is actually in storage.
"""

import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pymupdf
import pytest
from sqlalchemy import select, text

from app import config, limits
from app.main import app
from app.models import Profile, ResumeUpload
from app.services import pdf_worker, resume_parse, storage
from tests.conftest import (
    api_routes,
    make_pdf,
    make_scanned_pdf,
    presign,
    put_upload,
    register,
    upload_resume,
)

PDF = {"Content-Type": "application/pdf"}
KEY = re.compile(r"^resumes/1/[0-9a-f]{32}\.pdf$")


def stored(key: str) -> Path:
    return Path(config.UPLOAD_DIR) / key


def commit(client, headers, key, filename="resume.pdf"):
    return client.post(
        "/profile/resume/commit", json={"key": key, "filename": filename}, headers=headers
    )


def slots(db) -> list[ResumeUpload]:
    db.expire_all()
    return list(db.scalars(select(ResumeUpload).order_by(ResumeUpload.created_at)))


def assert_gone(db, key: str) -> None:
    """Refused means the file does not stay, and the slot cannot be reused."""
    assert not stored(key).exists()
    assert key not in {s.key for s in slots(db)}


# --------------------------------------------------------------------------- #
# Presign
# --------------------------------------------------------------------------- #


def test_presign_shape(client, auth):
    body = presign(client, auth, 4096, "Ada Resume.pdf")
    assert set(body) == {"upload_url", "key", "method", "headers"}
    assert body["method"] == "PUT"
    assert body["headers"] == {"Content-Type": "application/pdf", "Content-Length": "4096"}
    assert KEY.match(body["key"])
    assert body["upload_url"] == f"http://testserver/profile/resume/local/{body['key']}"


@pytest.mark.parametrize(
    "filename",
    [
        "Ada Resume.pdf",
        "../../../etc/passwd.pdf",
        "..\\..\\windows\\system32\\cmd.pdf",
        "résumé – final (2).pdf",
        "a" * 251 + ".pdf",
        "<script>alert(1)</script>.pdf",
        "resume.pdf\x00.exe.pdf",
        "%2e%2e%2f%2e%2e%2fsecrets.pdf",
    ],
)
def test_the_key_contains_nothing_the_client_sent(client, auth, db, filename):
    body = presign(client, auth, 4096, filename)
    assert KEY.match(body["key"]), body["key"]
    (slot,) = slots(db)
    # The name is kept, to show back; it is not part of any path.
    assert "/" not in slot.filename and "\\" not in slot.filename
    assert slot.filename.endswith(".pdf")
    random_part = body["key"].rsplit("/", 1)[-1].removesuffix(".pdf")
    assert re.fullmatch(r"[0-9a-f]{32}", random_part)
    for piece in re.findall(r"[A-Za-z]{4,}", filename):
        assert piece.lower() not in random_part, piece


def test_keys_are_not_guessable(client, auth):
    keys = {presign(client, auth, 4096)["key"] for _ in range(20)}
    assert len(keys) == 20
    assert len({k[-36:-4][:8] for k in keys}) == 20  # no shared prefix, no counter


@pytest.mark.parametrize(
    ("body", "words"),
    [
        ({"filename": "r.docx", "content_type": "application/pdf", "size": 4096}, "PDF"),
        ({"filename": "r.pdf", "content_type": "image/png", "size": 4096}, "PDF"),
        (
            {"filename": "r.pdf", "size": 4096, "content_type":
             "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
            "PDF",
        ),
        ({"filename": "r.pdf", "content_type": "application/pdf"}, "size: Field required"),
        ({"filename": "r.pdf", "content_type": "application/pdf", "size": 1023},
         "size: a resume must be between 1 KB and 5 MB"),
        ({"filename": "r.pdf", "content_type": "application/pdf", "size": 0},
         "size: a resume must be between 1 KB and 5 MB"),
        ({"filename": "r.pdf", "content_type": "application/pdf", "size": -1},
         "size: a resume must be between 1 KB and 5 MB"),
        ({"filename": "r.pdf", "content_type": "application/pdf", "size": 5 * 1024 * 1024 + 1},
         "size: a resume must be between 1 KB and 5 MB"),
        ({"filename": "r.pdf", "content_type": "application/pdf", "size": "big"}, "size: "),
    ],
)  # fmt: skip
def test_presign_refusals(client, auth, db, body, words):
    r = client.post("/profile/resume/presign", json=body, headers=auth)
    assert r.status_code == 422, r.text
    assert words in r.json()["detail"]
    assert slots(db) == []


@pytest.mark.parametrize("size", [1024, 5 * 1024 * 1024])
def test_presign_accepts_the_limits_themselves(client, auth, size):
    assert presign(client, auth, size)["headers"]["Content-Length"] == str(size)


def test_a_user_holds_one_unfinished_upload_at_a_time(client, auth, db):
    first = presign(client, auth, len(make_pdf()))
    assert put_upload(client, auth, first, make_pdf()).status_code == 204
    assert stored(first["key"]).exists()

    second = presign(client, auth, 4096)
    assert [s.key for s in slots(db)] == [second["key"]]
    assert not stored(first["key"]).exists()
    assert commit(client, auth, first["key"]).status_code == 404


def test_abandoned_uploads_are_swept(client, auth, db):
    other = register(client, email="gone@example.com")
    left = presign(client, other, len(make_pdf()))
    put_upload(client, other, left, make_pdf())
    db.execute(text("UPDATE resume_uploads SET expires_at = now() - interval '2 hours'"))
    db.commit()

    presign(client, auth, 4096)  # someone else, some time later
    assert_gone(db, left["key"])


# --------------------------------------------------------------------------- #
# The PUT
# --------------------------------------------------------------------------- #


def test_upload_is_stored_privately(client, auth):
    data = make_pdf()
    target = presign(client, auth, len(data))
    r = put_upload(client, auth, target, data)
    assert r.status_code == 204 and r.content == b""
    path = stored(target["key"])
    assert path.read_bytes() == data
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"


def test_upload_must_be_the_declared_size(client, auth, db):
    data = make_pdf()
    for declared, sent in [(len(data) + 1, data), (len(data) - 1, data), (2048, data)]:
        target = presign(client, auth, declared)
        r = put_upload(client, auth, target, sent)
        assert r.status_code == 400, (declared, r.status_code, r.text)
        assert r.json()["detail"] == (
            f"That upload link is for a file of exactly {declared:,} bytes. Start the upload again."
        )
        assert not stored(target["key"]).exists()
        # The slot was not used up by a failed attempt.
        assert slots(db)[-1].uploaded_at is None


def test_upload_is_counted_not_trusted(client, auth):
    """Chunked: no Content-Length at all. The limit has to hold against the
    bytes themselves, and reading has to stop when it is passed."""
    data = make_pdf()
    target = presign(client, auth, len(data))
    sent = []

    def too_many():
        for _ in range(200):
            sent.append(1)
            yield data

    r = put_upload(client, auth, target, too_many())
    assert r.status_code == 400
    assert "exactly" in r.json()["detail"]
    assert not stored(target["key"]).exists()

    def exactly():
        yield data[:500]
        yield data[500:]

    assert put_upload(client, auth, target, exactly()).status_code == 204


def test_upload_over_the_cap_is_413(client, auth, monkeypatch):
    target = presign(client, auth, 4096)
    monkeypatch.setattr(config, "RESUME_MAX_BYTES", 2048)
    r = put_upload(client, auth, target, b"%PDF-" + b"0" * 4091)
    assert r.status_code == 413
    assert r.json() == {"detail": "Resumes can be at most 0.00195312 MB."} or "at most" in r.text
    assert not stored(target["key"]).exists()


def test_upload_must_be_a_pdf_by_content_type(client, auth):
    data = make_pdf()
    target = presign(client, auth, len(data))
    for wrong in ("image/png", "application/octet-stream", "text/html"):
        r = put_upload(client, auth, target, data, **{"Content-Type": wrong})
        assert r.status_code == 415
    assert not stored(target["key"]).exists()


def test_a_slot_takes_one_upload(client, auth):
    data = make_pdf()
    target = presign(client, auth, len(data))
    assert put_upload(client, auth, target, data).status_code == 204

    other = b"%PDF-" + b"x" * (len(data) - 5)
    r = put_upload(client, auth, target, other)
    assert r.status_code == 409
    assert r.json() == {"detail": "That upload link has already been used. Start the upload again."}
    assert stored(target["key"]).read_bytes() == data


def test_a_slot_expires(client, auth, db):
    data = make_pdf()
    target = presign(client, auth, len(data))
    db.execute(text("UPDATE resume_uploads SET expires_at = now() - interval '1 second'"))
    db.commit()
    r = put_upload(client, auth, target, data)
    assert r.status_code == 410
    assert r.json() == {"detail": "That upload link has expired. Start the upload again."}
    assert not stored(target["key"]).exists()


def test_slots_are_short_lived(client, auth, db):
    presign(client, auth, 4096)
    (slot,) = slots(db)
    life = slot.expires_at - slot.created_at
    assert timedelta(seconds=60) <= life <= timedelta(seconds=config.PRESIGN_EXPIRY_SECONDS + 5)
    assert config.PRESIGN_EXPIRY_SECONDS <= 900


@pytest.mark.parametrize(
    "key",
    [
        "resumes/1/" + "0" * 32 + ".pdf",  # right shape, never issued
        "resumes/1/0123456789ab-resume.pdf",  # the old shape
        "resumes/1/../../etc/passwd",
        "resumes/1/abc.pdf",
        "resumes/2/" + "0" * 32 + ".pdf",
        "/etc/passwd",
        "resumes/1/" + "0" * 32 + ".pdf/../../x",
        "resumes/1/" + "0" * 32 + ".exe",
        "x" * 300,
    ],
)
def test_upload_without_a_slot_is_404(client, auth, key):
    """There is no writing to a key that was not issued, however well formed.
    This is what closes the open upload slot."""
    r = client.put(f"/profile/resume/local/{key}", content=make_pdf(), headers={**auth, **PDF})
    assert r.status_code == 404, (key, r.status_code)
    assert not any(Path(config.UPLOAD_DIR).rglob("*.*")), "something was written"


def test_upload_requires_the_token(client, auth):
    data = make_pdf()
    target = presign(client, auth, len(data))
    assert put_upload(client, {}, target, data).status_code == 401
    assert put_upload(client, {"Authorization": "Bearer nope"}, target, data).status_code == 401


# --------------------------------------------------------------------------- #
# Commit
# --------------------------------------------------------------------------- #


def test_full_flow_extracts_skills(client, auth, profile_body):
    r = upload_resume(client, auth, make_pdf(), "Ada Resume.pdf")
    assert r.status_code == 200, r.text
    resume = r.json()
    assert set(resume) == {"filename", "uploaded_at", "skills", "needs_ocr"}
    assert resume["filename"] == "Ada Resume.pdf" and resume["needs_ocr"] is False
    for skill in ["Python", "Java", "SQL", "C++", "React", "PyTorch", "scikit-learn", "AWS",
                  "Docker", "PostgreSQL", "Machine Learning", "REST", "CI/CD"]:  # fmt: skip
        assert skill in resume["skills"], skill

    client.put("/profile", json=profile_body, headers=auth)
    profile = client.get("/profile", headers=auth).json()
    assert profile["resume"] == resume
    assert profile["profile_version"] == 2  # commit bumped it, then the save did


def test_commit_without_upload_is_400(client, auth, db):
    target = presign(client, auth, 4096)
    r = commit(client, auth, target["key"])
    assert r.status_code == 400
    assert "Upload it first" in r.json()["detail"]
    assert [s.key for s in slots(db)] == [target["key"]]  # still usable


def test_commit_is_idempotent(client, auth):
    data = make_pdf()
    target = presign(client, auth, len(data))
    put_upload(client, auth, target, data)
    first = commit(client, auth, target["key"])
    again = commit(client, auth, target["key"])
    assert first.status_code == again.status_code == 200
    assert first.json() == again.json()


WORD_DOCUMENT = b"PK\x03\x04\x14\x00\x06\x00" + b"[Content_Types].xml word/document.xml " * 60
HTML = b"<!doctype html><script>alert(document.cookie)</script>" + b"<p>resume</p>" * 120
EXECUTABLE = b"MZ\x90\x00\x03\x00" + b"This program cannot be run in DOS mode. " * 40
SHELL = b"#!/bin/sh\nrm -rf /\n" + b"# " * 600
PDF_LATER = b"\n\n" + make_pdf()  # a PDF, but not from the first byte


@pytest.mark.parametrize(
    "data",
    [WORD_DOCUMENT, HTML, EXECUTABLE, SHELL, PDF_LATER, b"%PDF" + b"x" * 2000, b"\x00" * 2048],
    ids=["docx", "html", "exe", "shell", "pdf-not-at-byte-0", "almost-magic", "zeros"],
)
def test_a_renamed_file_is_refused_by_its_first_bytes(client, auth, db, data):
    """Named .pdf, declared application/pdf, and the right size. Only the
    content gives it away, and the content is what is checked."""
    target = presign(client, auth, len(data), "my-resume.pdf")
    assert put_upload(client, auth, target, data).status_code == 204
    r = commit(client, auth, target["key"], "my-resume.pdf")
    assert r.status_code == 400
    assert r.json() == {"detail": "That file isn't a PDF."}
    assert_gone(db, target["key"])
    assert db.get(Profile, 1) is None or db.get(Profile, 1).resume_s3_key is None


def test_a_file_that_is_not_a_pdf_never_reaches_the_parser(client, auth, monkeypatch):
    """The first bytes are read on their own, and the decision is made on
    them. The rest of the file is not fetched and no parser is started."""
    parsed, fetched = [], []
    monkeypatch.setattr(pdf_worker, "extract", lambda *a, **k: parsed.append(1))
    real_read = storage.read
    monkeypatch.setattr(storage, "read", lambda *a, **k: fetched.append(1) or real_read(*a, **k))

    target = presign(client, auth, len(WORD_DOCUMENT))
    put_upload(client, auth, target, WORD_DOCUMENT)
    r = commit(client, auth, target["key"])
    assert r.status_code == 400 and r.json() == {"detail": "That file isn't a PDF."}
    assert parsed == [] and fetched == []


def _locked_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 560, 780), "Python SQL " * 200)
    return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")


@pytest.mark.parametrize(
    ("data", "detail"),
    [
        (b"%PDF-1.7\n" + b"\x00\xff not really a pdf" * 80, pdf_worker.UNREADABLE),
        (b"%PDF-1.7\n%%EOF\n" + b" " * 1200, pdf_worker.UNREADABLE),
        (_locked_pdf(), pdf_worker.ENCRYPTED),
    ],
    ids=["garbage-after-header", "empty-document", "password-protected"],
)
def test_a_pdf_that_cannot_be_read_is_a_400_never_a_500(client, auth, db, data, detail):
    target = presign(client, auth, len(data))
    put_upload(client, auth, target, data)
    r = commit(client, auth, target["key"])
    assert r.status_code == 400, r.text
    assert r.json() == {"detail": detail}
    assert_gone(db, target["key"])


def test_a_pdf_that_will_not_finish_is_abandoned(client, auth, db, monkeypatch):
    monkeypatch.setattr(config, "RESUME_PARSE_TIMEOUT_S", 0.001)
    data = make_pdf()
    target = presign(client, auth, len(data))
    put_upload(client, auth, target, data)
    started = time.perf_counter()
    r = commit(client, auth, target["key"])
    assert time.perf_counter() - started < 2
    assert r.status_code == 400
    assert r.json() == {"detail": pdf_worker.TOO_SLOW}
    assert_gone(db, target["key"])


def test_a_parser_crash_is_contained(client, auth, db, monkeypatch):
    """A segfault in the C library kills the child, not the API."""

    def crashed(*args, **kwargs):
        return subprocess.CompletedProcess(args, returncode=-11, stdout=b"", stderr=b"")

    monkeypatch.setattr(pdf_worker.subprocess, "run", crashed)
    data = make_pdf()
    target = presign(client, auth, len(data))
    put_upload(client, auth, target, data)
    r = commit(client, auth, target["key"])
    assert r.status_code == 400
    assert r.json() == {"detail": pdf_worker.UNREADABLE}
    assert_gone(db, target["key"])
    assert client.get("/health").status_code == 200


@pytest.mark.parametrize(
    "reply",
    [b"", b"not json", b"[]", b'{"outcome": "ok"}', b'{"outcome": "pwned", "text": "x"}',
     b'{"outcome": "ok", "text": 5}'],
)  # fmt: skip
def test_the_worker_is_not_believed_either(monkeypatch, reply):
    monkeypatch.setattr(
        pdf_worker.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(a, returncode=0, stdout=reply, stderr=b""),
    )
    out = pdf_worker.extract(make_pdf(), max_pages=10, max_chars=100, seconds=5)
    assert out == (pdf_worker.UNREADABLE, "")


def test_the_worker_starts_with_nothing(monkeypatch):
    seen = {}

    def spy(cmd, **kwargs):
        seen.update(cmd=cmd, **kwargs)
        return subprocess.CompletedProcess(cmd, 0, b'{"outcome":"ok","text":"hi"}', b"")

    monkeypatch.setattr(pdf_worker.subprocess, "run", spy)
    monkeypatch.setenv("JWT_SECRET", "must-not-reach-the-child")
    assert pdf_worker.extract(make_pdf(), max_pages=3, max_chars=9, seconds=4) == ("ok", "hi")
    assert seen["env"] == {}
    assert "-I" in seen["cmd"] and seen["cmd"][2].endswith("pdf_worker.py")
    assert seen["timeout"] == 4


def test_reading_stops_at_the_page_and_character_caps():
    doc = pymupdf.open()
    for n in range(40):
        doc.new_page().insert_text((72, 72), f"page-{n} " + "word " * 40)
    outcome, text_ = pdf_worker.extract(doc.tobytes(), max_pages=10, max_chars=10**6, seconds=10)
    assert outcome == pdf_worker.OK
    assert text_.count("page-") == 10 and "page-10 " not in text_
    outcome, text_ = pdf_worker.extract(doc.tobytes(), max_pages=10, max_chars=300, seconds=10)
    assert outcome == pdf_worker.OK and len(text_) <= 300
    assert resume_parse.MAX_PAGES == 10 and resume_parse.MAX_CHARS == 100_000


def test_scanned_pdf_is_flagged_not_failed(client, auth):
    r = upload_resume(client, auth, make_scanned_pdf(), "scan.pdf")
    assert r.status_code == 200, r.text
    assert r.json()["needs_ocr"] is True and r.json()["skills"] == []


def test_commit_checks_what_is_stored_not_what_was_said(client, auth, db):
    """The object changed between upload and commit. The size recorded in
    the slot is a promise; the size in storage is a fact."""
    data = make_pdf()
    target = presign(client, auth, len(data))
    put_upload(client, auth, target, data)
    stored(target["key"]).write_bytes(data + b"%" * 512)

    r = commit(client, auth, target["key"])
    assert r.status_code == 400
    assert r.json() == {
        "detail": "That upload is not the file that was described. Start the upload again."
    }
    assert_gone(db, target["key"])


def test_commit_refuses_an_oversized_object(client, auth, db, monkeypatch):
    data = make_pdf()
    target = presign(client, auth, len(data))
    put_upload(client, auth, target, data)
    monkeypatch.setattr(config, "RESUME_MAX_BYTES", 1200)
    r = commit(client, auth, target["key"])
    assert r.status_code == 400 and "at most" in r.json()["detail"]
    assert_gone(db, target["key"])


def test_replacing_a_resume_deletes_the_old_object(client, auth, db):
    assert upload_resume(client, auth, make_pdf(), "a.pdf").status_code == 200
    first = db.get(Profile, 1).resume_s3_key
    assert stored(first).exists()

    second_pdf = make_pdf(extra="Also: Rust, Go, Kubernetes, Terraform")
    assert upload_resume(client, auth, second_pdf, "b.pdf").status_code == 200
    db.expire_all()
    second = db.get(Profile, 1).resume_s3_key
    assert second != first
    assert not stored(first).exists() and stored(second).exists()
    assert [s.key for s in slots(db)] == [second]
    assert (
        client.post(
            "/profile/resume/commit", json={"key": first, "filename": "a.pdf"}, headers=auth
        ).status_code
        == 404
    )


def test_a_resume_stored_under_an_old_key_still_works(client, auth, db, profile_body):
    """Keys issued before this change carried the filename. One such resume
    is already on disk. It must still be shown, and still be deleted when it
    is replaced."""
    old_key = "resumes/1/0123456789ab-My_Resume.pdf"
    assert upload_resume(client, auth, make_pdf(), "My Resume.pdf").status_code == 200
    client.put("/profile", json=profile_body, headers=auth)
    current = db.get(Profile, 1).resume_s3_key
    stored(current).rename(stored(old_key))
    db.execute(text("DELETE FROM resume_uploads"))
    db.execute(text("UPDATE profiles SET resume_s3_key = :k"), {"k": old_key})
    db.commit()

    shown = client.get("/profile", headers=auth).json()["resume"]
    assert shown["filename"] == "My Resume.pdf" and "Python" in shown["skills"]
    assert storage.owns(1, old_key) and storage.size(old_key) == len(make_pdf())
    # It cannot be uploaded to or committed again: it has no slot.
    assert (
        client.put(
            f"/profile/resume/local/{old_key}", content=make_pdf(), headers={**auth, **PDF}
        ).status_code
        == 404
    )
    assert commit(client, auth, old_key).status_code == 404
    assert stored(old_key).exists()

    newer = make_pdf(extra="Also: Kotlin, SwiftUI, Android")
    assert upload_resume(client, auth, newer, "new.pdf").status_code == 200
    assert not stored(old_key).exists()
    assert client.get("/profile", headers=auth).json()["resume"]["filename"] == "new.pdf"


def test_the_shown_filename_is_cleaned(client, auth):
    r = upload_resume(client, auth, make_pdf(), "..\\..\\evil/../My\tResume\x07.pdf")
    assert r.status_code == 200
    assert r.json()["filename"] == "My Resume.pdf"


# --------------------------------------------------------------------------- #
# Nothing serves a resume back
# --------------------------------------------------------------------------- #


def test_no_route_serves_a_resume(client, auth):
    from fastapi.responses import FileResponse, StreamingResponse

    routes = api_routes(app)
    assert len(routes) >= 20
    for (method, path), route in routes.items():
        if "resume" in path:
            assert method in ("POST", "PUT"), f"{method} {path} would read a resume back"
        response_class = getattr(route.response_class, "value", route.response_class)
        assert not issubclass(response_class, FileResponse | StreamingResponse), path

    upload_resume(client, auth)
    for path in ("/profile/resume", "/profile/resume/download", "/profile/resume/local"):
        assert client.get(path, headers=auth).status_code in (404, 405)


def test_no_response_carries_the_storage_key_or_the_text(client, auth, db, profile_body):
    upload_resume(client, auth)
    client.put("/profile", json=profile_body, headers=auth)
    key = db.get(Profile, 1).resume_s3_key
    for path in ("/profile", "/me", "/feed", "/saved", "/applications"):
        body = client.get(path, headers=auth).text
        assert key not in body and "resume_text" not in body and "resume_s3_key" not in body
        assert "University of Maryland, College Park - B.S." not in body  # the resume's text


# --------------------------------------------------------------------------- #
# S3: what the signature pins
# --------------------------------------------------------------------------- #


@pytest.fixture()
def s3(monkeypatch):
    monkeypatch.setattr(config, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(config, "S3_BUCKET", "step1-resumes-test")
    monkeypatch.setattr(config, "KMS_KEY_ID", "")
    # Signing happens locally; nothing here reaches AWS.
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAIOSFODNN7EXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")


def test_s3_url_is_signed_for_one_type_one_length_and_not_for_long(s3):
    key = storage.new_key(7)
    url, headers = storage.presign_put(key, "application/pdf", 71_973)
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https" and parsed.path.endswith(key)
    assert query["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    signed = query["X-Amz-SignedHeaders"][0].split(";")
    assert {"content-length", "content-type", "host", "x-amz-server-side-encryption"} <= set(signed)
    assert int(query["X-Amz-Expires"][0]) == config.PRESIGN_EXPIRY_SECONDS <= 900
    assert headers == {
        "Content-Type": "application/pdf",
        "Content-Length": "71973",
        "x-amz-server-side-encryption": "AES256",
    }

    # A different length is a different signature: the URL cannot be reused
    # for a larger file.
    other, _ = storage.presign_put(key, "application/pdf", 71_974)
    assert parse_qs(urlparse(other).query)["X-Amz-Signature"] != query["X-Amz-Signature"]


def test_s3_uses_the_kms_key_when_there_is_one(s3, monkeypatch):
    monkeypatch.setattr(config, "KMS_KEY_ID", "arn:aws:kms:us-east-1:111122223333:key/abcd")
    url, headers = storage.presign_put(storage.new_key(7), "application/pdf", 4096)
    signed = parse_qs(urlparse(url).query)["X-Amz-SignedHeaders"][0].split(";")
    assert "x-amz-server-side-encryption-aws-kms-key-id" in signed
    assert headers["x-amz-server-side-encryption"] == "aws:kms"
    assert headers["x-amz-server-side-encryption-aws-kms-key-id"] == config.KMS_KEY_ID


def test_s3_presign_through_the_api(client, auth, s3):
    r = client.post(
        "/profile/resume/presign",
        json={"filename": "r.pdf", "content_type": "application/pdf", "size": 4096},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "X-Amz-Signature=" in body["upload_url"]
    assert body["key"] in body["upload_url"] and KEY.match(body["key"])
    # The local upload route does not exist in S3 mode.
    assert (
        client.put(
            f"/profile/resume/local/{body['key']}", content=b"x" * 4096, headers={**auth, **PDF}
        ).status_code
        == 404
    )


# --------------------------------------------------------------------------- #
# Skills
# --------------------------------------------------------------------------- #


def test_skill_matcher_avoids_lookalikes():
    words = "John C. Smith led R&D and go-to-market. I excel at the rest. TS/SCI. Spring 2027."
    assert resume_parse.find_skills(words) == []
    assert resume_parse.find_skills("Java") == ["Java"]
    assert resume_parse.find_skills("JavaScript") == ["JavaScript"]
    assert resume_parse.find_skills("C, C++, C#, Go, R, .NET") == [
        "C",
        "C++",
        "C#",
        "Go",
        "R",
        ".NET",
    ]
    assert resume_parse.find_skills("react native and k8s") == ["React Native", "Kubernetes"]
    assert 180 <= len(resume_parse.SKILLS) <= 260


def test_limits_are_what_the_readme_says():
    assert limits.RESUME_MIN_BYTES == 1024
    assert config.RESUME_MAX_BYTES == 5 * 1024 * 1024
    assert datetime.now(UTC).year >= 2026
