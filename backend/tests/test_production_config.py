"""Production refuses to start with settings that are only safe on a laptop."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import config

BACKEND = Path(__file__).resolve().parent.parent
GOOD_SECRET = "k" * 48
SAFE = dict(
    auth_mode="local",
    jwt_secret=GOOD_SECRET,
    bcrypt_rounds=12,
    allowed_origins=["https://step1.example"],
)


def problems(**over) -> list[str]:
    return config.production_problems(**(SAFE | over))


def test_sound_settings_have_no_problems():
    assert problems() == []


def test_the_default_secret_is_refused():
    (problem,) = problems(jwt_secret=config.DEFAULT_JWT_SECRET)
    assert "JWT_SECRET is the development default" in problem
    assert "secrets.token_urlsafe" in problem  # says what to do instead
    assert config.DEFAULT_JWT_SECRET not in problem


@pytest.mark.parametrize("secret", ["", "short", "x" * 31])
def test_a_short_secret_is_refused(secret):
    (problem,) = problems(jwt_secret=secret)
    assert "must be at least 32" in problem
    assert secret == "" or secret not in problem  # a secret is never printed


def test_a_secret_of_exactly_the_minimum_is_accepted():
    assert problems(jwt_secret="x" * 32) == []


def test_cognito_does_not_need_our_secret():
    """In cognito mode the pool signs the tokens; ours is never used."""
    assert problems(auth_mode="cognito", jwt_secret=config.DEFAULT_JWT_SECRET) == []


def test_weak_hashing_and_open_cors_are_refused():
    assert "BCRYPT_ROUNDS is 4" in problems(bcrypt_rounds=4)[0]
    assert problems(bcrypt_rounds=10) == []
    assert "ALLOWED_ORIGINS contains '*'" in problems(allowed_origins=["*"])[0]


def test_every_problem_is_reported_at_once():
    found = problems(jwt_secret=config.DEFAULT_JWT_SECRET, bcrypt_rounds=4, allowed_origins=["*"])
    assert len(found) == 3


def test_development_is_not_checked():
    assert config.APP_ENV == "dev"
    config._check_production()  # does nothing, raises nothing


def start(**env) -> subprocess.CompletedProcess:
    """Import the settings in a fresh process, as a server starting would."""
    clean = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        # Settings come only from here: nothing on this machine that could
        # supply credentials or reach AWS is visible to the child.
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
        "AWS_CONFIG_FILE": os.devnull,
        "DATABASE_URL": "postgresql+psycopg://localhost:5432/not_used",
        "AUTH_MODE": "local",
        "BCRYPT_ROUNDS": "12",
        "ALLOWED_ORIGINS": "https://step1.example",
        "TRUST_PROXY": "true",
        "STORAGE_BACKEND": "local",
        "RATE_LIMIT_ENABLED": "true",
        "AUTO_INGEST": "false",
        **env,
    }
    return subprocess.run(
        [sys.executable, "-c", "import app.config as c; print('started', c.APP_ENV)"],
        cwd=BACKEND,
        env=clean,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_production_does_not_start_on_the_default_secret():
    done = start(APP_ENV="prod", JWT_SECRET=config.DEFAULT_JWT_SECRET)
    assert done.returncode != 0
    assert "started" not in done.stdout
    assert "Refusing to start with APP_ENV=prod" in done.stderr
    assert "JWT_SECRET is the development default" in done.stderr


def test_production_starts_on_a_real_secret():
    done = start(APP_ENV="prod", JWT_SECRET=GOOD_SECRET)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "started prod"
    assert GOOD_SECRET not in done.stderr


def test_development_starts_on_the_default_secret():
    done = start(APP_ENV="dev", JWT_SECRET=config.DEFAULT_JWT_SECRET)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "started dev"


def test_production_warns_about_what_weakens_a_protection():
    done = start(
        APP_ENV="prod", JWT_SECRET=GOOD_SECRET, TRUST_PROXY="false", RATE_LIMIT_ENABLED="false"
    )
    assert done.returncode == 0, done.stderr
    assert "TRUST_PROXY is false in production" in done.stderr
    assert "STORAGE_BACKEND is local in production" in done.stderr
    assert "sign-in is not throttled" in done.stderr
