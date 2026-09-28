"""Resume flow: presign -> upload -> commit, in local storage mode."""

import pymupdf

from app import config
from app.services import resume_parse
from tests.conftest import make_pdf, register

PDF = {"Content-Type": "application/pdf"}


def _presign(client, auth, filename="Ada Resume.pdf", content_type="application/pdf"):
    return client.post(
        "/profile/resume/presign",
        json={"filename": filename, "content_type": content_type},
        headers=auth,
    )


def _upload(client, auth, presigned, data):
    path = presigned["upload_url"].removeprefix(config.PUBLIC_API_BASE)
    return client.put(path, content=data, headers={**auth, **presigned["headers"]})


def test_presign_shape(client, auth):
    r = _presign(client, auth)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"upload_url", "key", "method", "headers"}
    assert body["method"] == "PUT"
    assert body["headers"] == {"Content-Type": "application/pdf"}
    assert body["key"].startswith("resumes/1/") and body["key"].endswith("-Ada_Resume.pdf")
    assert body["upload_url"] == f"http://testserver/profile/resume/local/{body['key']}"


def test_presign_rejects_non_pdf(client, auth):
    for filename, ctype in [("resume.docx", "application/pdf"), ("resume.pdf", "image/png")]:
        r = _presign(client, auth, filename, ctype)
        assert r.status_code == 422
        assert "PDF" in r.json()["detail"]


def test_full_flow_extracts_skills(client, auth, profile_body):
    presigned = _presign(client, auth).json()
    up = _upload(client, auth, presigned, make_pdf())
    assert up.status_code == 200, up.text

    r = client.post(
        "/profile/resume/commit",
        json={"key": presigned["key"], "filename": "Ada Resume.pdf"},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    resume = r.json()
    assert set(resume) == {"filename", "uploaded_at", "skills", "needs_ocr"}
    assert resume["filename"] == "Ada Resume.pdf" and resume["needs_ocr"] is False
    for skill in ["Python", "Java", "SQL", "C++", "React", "PyTorch", "scikit-learn", "AWS",
                  "Docker", "PostgreSQL", "Machine Learning", "REST", "CI/CD"]:  # fmt: skip
        assert skill in resume["skills"], skill

    # The resume survives onboarding and shows up on the profile.
    client.put("/profile", json=profile_body, headers=auth)
    profile = client.get("/profile", headers=auth).json()
    assert profile["resume"]["skills"] == resume["skills"]
    assert profile["profile_version"] == 2  # commit bumped it, then the save did


def test_commit_without_upload_is_400(client, auth):
    presigned = _presign(client, auth).json()
    r = client.post(
        "/profile/resume/commit",
        json={"key": presigned["key"], "filename": "resume.pdf"},
        headers=auth,
    )
    assert r.status_code == 400
    assert "Upload it first" in r.json()["detail"]


def test_image_only_pdf_is_flagged_not_failed(client, auth):
    doc = pymupdf.open()
    doc.new_page()  # a page with no text layer
    blank = doc.tobytes()
    presigned = _presign(client, auth).json()
    _upload(client, auth, presigned, blank)
    r = client.post(
        "/profile/resume/commit",
        json={"key": presigned["key"], "filename": "scan.pdf"},
        headers=auth,
    )
    assert r.status_code == 200
    assert r.json()["needs_ocr"] is True and r.json()["skills"] == []


def test_not_a_pdf_is_400(client, auth):
    presigned = _presign(client, auth).json()
    _upload(client, auth, presigned, b"PK\x03\x04 this is a docx wearing a pdf name")
    r = client.post(
        "/profile/resume/commit",
        json={"key": presigned["key"], "filename": "resume.pdf"},
        headers=auth,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "That file is not a PDF."


def test_upload_over_limit_is_413(client, auth, monkeypatch):
    monkeypatch.setattr(config, "RESUME_MAX_BYTES", 1024)
    presigned = _presign(client, auth).json()
    r = _upload(client, auth, presigned, make_pdf() + b"0" * 2048)
    assert r.status_code == 413
    assert isinstance(r.json()["detail"], str)


def test_upload_requires_auth_and_ownership(client, auth):
    presigned = _presign(client, auth).json()
    path = presigned["upload_url"].removeprefix(config.PUBLIC_API_BASE)
    assert client.put(path, content=make_pdf(), headers=PDF).status_code == 401

    mallory = register(client, email="mallory@umd.edu")
    assert client.put(path, content=make_pdf(), headers={**mallory, **PDF}).status_code == 404
    _upload(client, auth, presigned, make_pdf())
    r = client.post(
        "/profile/resume/commit",
        json={"key": presigned["key"], "filename": "resume.pdf"},
        headers=mallory,
    )
    assert r.status_code == 404


def test_path_traversal_keys_are_refused(client, auth):
    for key in ["resumes/1/../../etc/passwd", "resumes/1/abc.pdf", "/etc/passwd"]:
        r = client.put(f"/profile/resume/local/{key}", content=make_pdf(), headers={**auth, **PDF})
        assert r.status_code == 404, key


def test_replacing_a_resume_deletes_the_old_object(client, auth):
    from app.services import storage

    first = _presign(client, auth).json()
    _upload(client, auth, first, make_pdf())
    client.post(
        "/profile/resume/commit", json={"key": first["key"], "filename": "a.pdf"}, headers=auth
    )
    second = _presign(client, auth).json()
    _upload(client, auth, second, make_pdf())
    client.post(
        "/profile/resume/commit", json={"key": second["key"], "filename": "b.pdf"}, headers=auth
    )
    assert not storage.exists(first["key"]) and storage.exists(second["key"])


def test_skill_matcher_avoids_lookalikes():
    text = "John C. Smith led R&D and go-to-market. I excel at the rest. TS/SCI. Spring 2027."
    assert resume_parse.find_skills(text) == []
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
