"""Local-mode auth contract: register / login / me."""


def _register(client, email="ada@umd.edu", password="correct-horse", name="Ada"):
    return client.post(
        "/auth/register", json={"email": email, "password": password, "display_name": name}
    )


def test_register_returns_token_and_user(client):
    r = _register(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"] == {"id": 1, "email": "ada@umd.edu", "display_name": "Ada"}


def test_register_duplicate_is_409(client):
    assert _register(client).status_code == 200
    r = _register(client, email="ADA@umd.edu")  # case-insensitive
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


def test_register_short_password_is_422_with_flat_detail(client):
    r = _register(client, password="short")
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, str)
    assert "password" in detail and "8 characters" in detail


def test_login_and_me(client):
    _register(client)
    r = client.post("/auth/login", json={"email": "ada@umd.edu", "password": "correct-horse"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json() == {
        "id": 1,
        "email": "ada@umd.edu",
        "display_name": "Ada",
        "onboarded": False,
        "is_admin": False,
    }


def test_bad_login_is_401(client):
    _register(client)
    r = client.post("/auth/login", json={"email": "ada@umd.edu", "password": "wrong-password"})
    assert r.status_code == 401
    assert r.json() == {"detail": "Incorrect email or password."}
    r = client.post("/auth/login", json={"email": "nobody@umd.edu", "password": "wrong-password"})
    assert r.status_code == 401


def test_me_without_token_is_401(client):
    r = client.get("/me")
    assert r.status_code == 401
    assert r.json() == {"detail": "Not authenticated."}
    r = client.get("/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


def test_password_hash_is_bcrypt(db, client):
    from app.models import User

    _register(client)
    user = db.get(User, 1)
    assert user.password_hash.startswith("$2b$")
    assert "correct-horse" not in user.password_hash
