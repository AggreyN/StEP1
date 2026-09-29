"""Production refuses to start on a setting that is missing or only safe on a
laptop, and says which variable to change."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import config

BACKEND = Path(__file__).resolve().parent.parent
GOOD_SECRET = "k" * 48
GOOD_DATABASE = (
    "postgresql+psycopg://step1:a-long-generated-password@"
    "step1.abc123.us-east-1.rds.amazonaws.com:5432/step1?sslmode=require"
)
SAFE = dict(
    auth_mode="local",
    jwt_secret=GOOD_SECRET,
    bcrypt_rounds=12,
    allowed_origins=["https://step1.example"],
    database_url=GOOD_DATABASE,
    public_api_base="https://api.step1.example",
    storage_backend="s3",
    s3_bucket="step1-resumes-ab12cd",
    cognito_user_pool_id="",
    cognito_app_client_id="",
    cognito_jwks_url="",
    cognito_jwks_path="",
    aws_region="us-east-1",
    auto_ingest_set=True,
)
COGNITO = dict(
    auth_mode="cognito",
    jwt_secret=config.DEFAULT_JWT_SECRET,
    cognito_user_pool_id="us-east-1_AbCdEf123",
    cognito_app_client_id="1example23456789",
    cognito_jwks_url="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_AbCdEf123/.well-known/jwks.json",
)


def problems(**over) -> list[str]:
    return config.production_problems(**(SAFE | over))


def only(**over) -> str:
    found = problems(**over)
    assert len(found) == 1, found
    return found[0]


def test_sound_settings_have_no_problems():
    assert problems() == []
    assert problems(**COGNITO) == []


# --------------------------------------------------------------------------- #
# Each variable, and that the message names it
# --------------------------------------------------------------------------- #


def test_the_default_secret_is_refused():
    problem = only(jwt_secret=config.DEFAULT_JWT_SECRET)
    assert problem.startswith("JWT_SECRET is the development default")
    assert "secrets.token_urlsafe" in problem  # says what to do instead
    assert config.DEFAULT_JWT_SECRET not in problem


@pytest.mark.parametrize("secret", ["", "short", "x" * 31])
def test_a_short_secret_is_refused(secret):
    problem = only(jwt_secret=secret)
    assert problem.startswith("JWT_SECRET ") and "must be at least 32" in problem
    assert secret == "" or secret not in problem  # a secret is never printed


def test_a_secret_of_exactly_the_minimum_is_accepted():
    assert problems(jwt_secret="x" * 32) == []


def test_weak_hashing_is_refused():
    assert only(bcrypt_rounds=4).startswith("BCRYPT_ROUNDS is 4")
    assert problems(bcrypt_rounds=10) == []


@pytest.mark.parametrize(
    ("url", "words"),
    [
        ("", "DATABASE_URL is not set"),
        ("   ", "DATABASE_URL is not set"),
        (config.DEFAULT_DATABASE_URL, "DATABASE_URL points at this machine"),
        ("postgresql+psycopg://u:p@localhost:5432/step1?sslmode=require",
         "DATABASE_URL points at this machine"),
        ("postgresql+psycopg://u:p@127.0.0.1/step1?sslmode=require",
         "DATABASE_URL points at this machine"),
        ("postgresql+psycopg://u:p@db.example.com:5432/step1",
         "DATABASE_URL does not require TLS"),
        ("postgresql+psycopg://u:p@db.example.com:5432/step1?sslmode=prefer",
         "DATABASE_URL does not require TLS"),
        ("postgresql+psycopg://u:p@db.example.com:5432/step1?sslmode=disable",
         "DATABASE_URL does not require TLS"),
        ("postgresql+psycopg://u@db.example.com:5432/step1?sslmode=require",
         "DATABASE_URL has no password"),
        ("sqlite:///step1.db", "DATABASE_URL uses the driver 'sqlite'"),
        ("mysql://u:p@db.example.com/step1?sslmode=require", "DATABASE_URL uses the driver"),
        ("not a url at all", "DATABASE_URL could not be read"),
    ],
)  # fmt: skip
def test_database_url(url, words):
    found = problems(database_url=url)
    assert any(p.startswith(words) for p in found), found
    assert all(p.startswith("DATABASE_URL") for p in found)


@pytest.mark.parametrize("mode", ["require", "verify-ca", "verify-full"])
def test_database_url_with_tls_is_accepted(mode):
    assert problems(database_url=GOOD_DATABASE.replace("require", mode)) == []


def test_the_database_password_is_never_printed():
    password = "hunter2-very-secret-value"
    for url in (
        f"postgresql+psycopg://step1:{password}@localhost:5432/step1",
        f"postgresql+psycopg://step1:{password}@db.example.com/step1",
        f"mysql://step1:{password}@db.example.com/step1",
    ):
        found = problems(database_url=url)
        assert found and not any(password in p for p in found)
        assert not any("db.example.com" in p for p in found)


@pytest.mark.parametrize(
    ("origins", "words"),
    [
        ([], "ALLOWED_ORIGINS is empty"),
        (["*"], "ALLOWED_ORIGINS contains '*'"),
        (["http://localhost:3000"], "ALLOWED_ORIGINS contains 'http://localhost:3000', which is "
                                    "not https"),
        (["https://localhost:3000"], "ALLOWED_ORIGINS contains 'https://localhost:3000', which "
                                     "points at this machine"),
        (["http://step1.example"], "which is not https"),
        (["step1.example"], "which is not https"),
        (["https://step1.example/app"], "Give the origin only"),
        (["https://step1.example", "http://localhost:3000"], "which is not https"),
    ],
)  # fmt: skip
def test_allowed_origins(origins, words):
    problem = only(allowed_origins=origins)
    assert problem.startswith("ALLOWED_ORIGINS") and words in problem


def test_several_good_origins_are_accepted():
    assert problems(allowed_origins=["https://step1.example", "https://www.step1.example"]) == []
    assert problems(allowed_origins=["https://step1.example/"]) == []


@pytest.mark.parametrize(
    ("base", "words"),
    [
        ("", "PUBLIC_API_BASE is not set"),
        ("http://localhost:8000", "which is not https"),
        ("http://api.step1.example", "which is not https"),
        ("https://127.0.0.1:8000", "which points at this machine"),
        ("https://api.step1.example/v1", "Give the origin only"),
    ],
)
def test_public_api_base(base, words):
    problem = only(public_api_base=base)
    assert problem.startswith("PUBLIC_API_BASE") and words in problem


def test_s3_needs_a_bucket():
    assert only(s3_bucket="").startswith("S3_BUCKET is not set, and STORAGE_BACKEND is s3")
    assert problems(storage_backend="local", s3_bucket="") == []  # warned about, not refused


def test_cognito_needs_its_pool_and_client():
    found = problems(**COGNITO | dict(cognito_user_pool_id="", cognito_app_client_id=""))
    assert [p.split(" ")[0] for p in found] == ["COGNITO_USER_POOL_ID", "COGNITO_APP_CLIENT_ID"]
    assert only(**COGNITO | dict(cognito_app_client_id="")).startswith(
        "COGNITO_APP_CLIENT_ID is not set, and AUTH_MODE is cognito"
    )


def test_cognito_pool_must_be_in_the_configured_region():
    problem = only(**COGNITO | dict(aws_region="us-west-2"))
    assert problem.startswith("COGNITO_USER_POOL_ID does not begin with us-west-2_")


def test_cognito_keys_are_fetched_over_https_or_read_from_a_file():
    insecure = "http://keys.internal/jwks.json"
    assert only(**COGNITO | dict(cognito_jwks_url=insecure)).startswith(
        "COGNITO_JWKS_URL is not https"
    )
    # A file takes precedence, so the URL is not used and not judged.
    assert problems(**COGNITO | dict(cognito_jwks_url=insecure, cognito_jwks_path="/k.json")) == []


def test_cognito_does_not_need_our_secret():
    """In cognito mode the pool signs the tokens; ours is never used."""
    assert problems(**COGNITO) == []


def test_auto_ingest_has_to_be_said_out_loud():
    problem = only(auto_ingest_set=False)
    assert problem.startswith("AUTO_INGEST is not set")
    assert "never refresh" in problem


def test_every_problem_is_reported_at_once_and_names_its_variable():
    found = problems(
        jwt_secret=config.DEFAULT_JWT_SECRET,
        bcrypt_rounds=4,
        allowed_origins=["*"],
        database_url="",
        public_api_base="",
        s3_bucket="",
        auto_ingest_set=False,
    )
    named = [p.split(" ")[0] for p in found]
    assert named == [
        "DATABASE_URL", "JWT_SECRET", "BCRYPT_ROUNDS", "ALLOWED_ORIGINS", "PUBLIC_API_BASE",
        "S3_BUCKET", "AUTO_INGEST",
    ]  # fmt: skip


def test_development_is_not_checked():
    assert config.APP_ENV == "dev"
    config._check_production()  # does nothing, raises nothing


# --------------------------------------------------------------------------- #
# A real start, in a fresh process
# --------------------------------------------------------------------------- #

PRODUCTION = {
    "APP_ENV": "prod",
    "SECRETS_BACKEND": "env",
    "DATABASE_URL": GOOD_DATABASE,
    "AUTH_MODE": "local",
    "JWT_SECRET": GOOD_SECRET,
    "BCRYPT_ROUNDS": "12",
    "ALLOWED_ORIGINS": "https://step1.example",
    "PUBLIC_API_BASE": "https://api.step1.example",
    "STORAGE_BACKEND": "s3",
    "S3_BUCKET": "step1-resumes-ab12cd",
    "AWS_REGION": "us-east-1",
    "TRUST_PROXY": "true",
    "TRUSTED_PROXY_HOPS": "1",
    "RATE_LIMIT_ENABLED": "true",
    "AUTO_INGEST": "true",
}


def start(env: dict, without: tuple = ()) -> subprocess.CompletedProcess:
    """Import the settings in a fresh process, as a server starting would.
    Nothing on this machine that could supply settings, credentials or a way
    to reach AWS is visible to it."""
    clean = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "AWS_EC2_METADATA_DISABLED": "true",
        "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
        "AWS_CONFIG_FILE": os.devnull,
        **env,
    }
    for name in without:
        clean.pop(name, None)
    return subprocess.run(
        [sys.executable, "-c", "import app.config as c; print('started', c.APP_ENV)"],
        cwd=BACKEND,
        env=clean,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_documented_production_settings_start():
    done = start(PRODUCTION)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "started prod"
    assert GOOD_SECRET not in done.stderr and "a-long-generated-password" not in done.stderr


@pytest.mark.parametrize(
    "missing",
    ["DATABASE_URL", "JWT_SECRET", "ALLOWED_ORIGINS", "PUBLIC_API_BASE", "S3_BUCKET",
     "AUTO_INGEST"],
)  # fmt: skip
def test_production_does_not_start_without(missing):
    """Leaving a variable out must not quietly fall back to the value that
    suits a laptop."""
    done = start(PRODUCTION, without=(missing,))
    assert done.returncode != 0
    assert "started" not in done.stdout
    assert "Refusing to start with APP_ENV=prod" in done.stderr
    assert f"  - {missing} " in done.stderr, done.stderr[-600:]


def test_production_does_not_start_on_the_default_secret():
    done = start(PRODUCTION | {"JWT_SECRET": config.DEFAULT_JWT_SECRET})
    assert done.returncode != 0
    assert "JWT_SECRET is the development default" in done.stderr


def test_production_cognito_needs_pool_and_client():
    cognito = PRODUCTION | {"AUTH_MODE": "cognito"}
    done = start(cognito, without=("JWT_SECRET",))
    assert done.returncode != 0
    assert "  - COGNITO_USER_POOL_ID is not set" in done.stderr
    assert "  - COGNITO_APP_CLIENT_ID is not set" in done.stderr

    done = start(
        cognito
        | {"COGNITO_USER_POOL_ID": "us-east-1_AbCdEf123", "COGNITO_APP_CLIENT_ID": "1example2345"},
        without=("JWT_SECRET",),
    )
    assert done.returncode == 0, done.stderr


def test_development_starts_with_nothing_set():
    done = start({"APP_ENV": "dev"})
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "started dev"


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("APP_ENV", "production"),  # would otherwise run as dev, unchecked
        ("APP_ENV", "staging"),
        ("AUTH_MODE", "cognit"),  # would otherwise run as local auth
        ("AUTH_MODE", "none"),
        ("STORAGE_BACKEND", "S3 "),
        ("STORAGE_BACKEND", "gcs"),
        ("SECRETS_BACKEND", "vault"),
    ],
)
def test_a_misspelt_choice_stops_the_start_everywhere(name, value):
    done = start({"APP_ENV": "dev", name: value})
    if value.strip().lower() in ("s3",):
        assert done.returncode == 0  # case and spaces are forgiven; words are not
        return
    assert done.returncode != 0
    assert f"{name}=" in done.stderr and "Refusing to guess" in done.stderr


def test_production_warns_about_what_weakens_a_protection():
    done = start(
        PRODUCTION
        | {"TRUST_PROXY": "false", "RATE_LIMIT_ENABLED": "false", "STORAGE_BACKEND": "local"}
    )
    assert done.returncode == 0, done.stderr
    assert "TRUST_PROXY is false in production" in done.stderr
    assert "STORAGE_BACKEND is local in production" in done.stderr
    assert "sign-in is not throttled" in done.stderr


def test_secrets_come_from_the_environment_unless_asked_otherwise(tmp_path):
    """With SECRETS_BACKEND=env, as on ECS, starting makes no AWS call at all:
    no credentials are looked for and nothing is logged about them."""
    done = start(PRODUCTION)
    assert done.returncode == 0
    assert "Secrets Manager" not in done.stderr

    # Asked for, and unreachable: it says so by name and falls back.
    done = start(PRODUCTION | {"SECRETS_BACKEND": "secretsmanager"})
    assert done.returncode == 0, done.stderr
    assert "Secrets Manager lookup failed for step1/DATABASE_URL" in done.stderr
    assert GOOD_SECRET not in done.stderr


# --------------------------------------------------------------------------- #
# The keys file
# --------------------------------------------------------------------------- #


def test_a_missing_or_empty_keys_file_stops_the_start(tmp_path):
    cognito = {
        "APP_ENV": "dev",
        "AUTH_MODE": "cognito",
        "COGNITO_USER_POOL_ID": "us-east-1_AbCdEf123",
        "COGNITO_APP_CLIENT_ID": "1example2345",
    }
    done = start(cognito | {"COGNITO_JWKS_PATH": str(tmp_path / "absent.json")})
    assert done.returncode != 0 and "COGNITO_JWKS_PATH=" in done.stderr

    for content in ("", "not json", "{}", '{"keys": []}', '{"keys": "x"}'):
        path = tmp_path / "keys.json"
        path.write_text(content)
        done = start(cognito | {"COGNITO_JWKS_PATH": str(path)})
        assert done.returncode != 0, content
        assert "could not be used" in done.stderr

    path.write_text(json.dumps({"keys": [{"kid": "k1", "kty": "RSA", "n": "AQAB", "e": "AQAB"}]}))
    assert start(cognito | {"COGNITO_JWKS_PATH": str(path)}).returncode == 0


# --------------------------------------------------------------------------- #
# The example file is the documentation, so it has to be true
# --------------------------------------------------------------------------- #


def _example() -> dict[str, str]:
    values = {}
    for line in (BACKEND / ".env.production.example").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            name, _, value = line.partition("=")
            values[name.strip()] = value.strip()
    return values


def test_the_production_example_lists_every_setting_the_app_reads():
    source = (BACKEND / "app" / "config.py").read_text()
    source += (BACKEND / "app" / "services" / "secrets.py").read_text()
    import re

    read = set(re.findall(r'(?:os\.getenv|get_secret)\(\s*"([A-Z0-9_]+)"', source))
    read |= set(re.findall(r'"([A-Z0-9_]+)" in os\.environ', source))
    assert len(read) > 40, read
    # Settings that only make sense on a laptop or under test.
    development_only = {"TEST_DATABASE_URL"}
    example = _example()
    commented = set(
        re.findall(r"^#\s*([A-Z0-9_]+)=", (BACKEND / ".env.production.example").read_text(), re.M)
    )
    missing = read - set(example) - commented - development_only
    assert not missing, f".env.production.example does not mention: {sorted(missing)}"


def test_the_production_example_holds_no_real_secrets():
    example = _example()
    placeholder = ("<", "CHANGE-ME")
    for name in ("DATABASE_URL", "JWT_SECRET", "S3_BUCKET"):
        assert any(mark in example[name] for mark in placeholder), name
    assert config.DEFAULT_JWT_SECRET not in (BACKEND / ".env.production.example").read_text()
    # The domain is the project's own, fixed no matter who deploys it, not a
    # per-deployment secret — so unlike the above, it is real here.
    assert example["ALLOWED_ORIGINS"] == "https://step1careers.com"
    assert example["PUBLIC_API_BASE"] == "https://api.step1careers.com"


def test_the_production_example_starts_once_its_placeholders_are_filled():
    filled = _example() | {
        "DATABASE_URL": GOOD_DATABASE,
        "JWT_SECRET": GOOD_SECRET,
        "S3_BUCKET": "step1-resumes-ab12cd",
    }
    assert filled["APP_ENV"] == "prod" and filled["TRUST_PROXY"] == "true"
    assert filled["TRUSTED_PROXY_HOPS"] == "1" and filled["AUTO_INGEST"] == "true"
    assert filled["STORAGE_BACKEND"] == "s3" and filled["SECRETS_BACKEND"] == "env"
    done = start(filled)
    assert done.returncode == 0, done.stderr
    assert "WARNING" not in done.stderr, done.stderr


def test_the_production_example_as_written_does_not_start():
    """Copied and not edited, it must fail rather than run on placeholder
    secrets. The placeholder for JWT_SECRET is long enough to pass for a
    real one, and it is published with the code. ALLOWED_ORIGINS and
    PUBLIC_API_BASE are not placeholders: the domain is fixed for this
    project, so the example already carries it rather than a stand-in."""
    done = start(_example())
    assert done.returncode != 0
    assert "Refusing to start with APP_ENV=prod" in done.stderr
    for name in ("DATABASE_URL", "JWT_SECRET", "S3_BUCKET"):
        assert f"  - {name} still holds the placeholder" in done.stderr, name
    assert "ALLOWED_ORIGINS" not in done.stderr
    assert "PUBLIC_API_BASE" not in done.stderr
    assert "CHANGE-ME" not in done.stderr  # not even a placeholder is echoed


@pytest.mark.parametrize(
    "over",
    [
        {"jwt_secret": "<CHANGE-ME-generate-a-long-random-value>"},
        {"database_url": GOOD_DATABASE.replace("a-long-generated-password", "<password>")},
        {"s3_bucket": "<bucket>"},
        {"allowed_origins": ["https://<domain>"]},
        {"public_api_base": "https://api.<domain>"},
        COGNITO | {"cognito_user_pool_id": "us-east-1_<pool>"},
    ],
)
def test_a_placeholder_is_not_a_value(over):
    found = problems(**over)
    assert len(found) == 1 and "still holds the placeholder" in found[0], found
    assert "CHANGE-ME" not in found[0] and "<" not in found[0]


def test_a_placeholder_does_not_hide_the_other_problems():
    found = problems(
        jwt_secret="<CHANGE-ME-generate-a-long-random-value>",
        database_url="postgresql+psycopg://u:p@db.example.com/step1",
        bcrypt_rounds=4,
    )
    assert [p.split(" ")[0] for p in found] == ["DATABASE_URL", "JWT_SECRET", "BCRYPT_ROUNDS"]
    assert "does not require TLS" in found[0] and "placeholder" in found[1]
