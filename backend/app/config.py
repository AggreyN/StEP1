"""Environment-driven settings for the StEP1 backend.

The one place that reads configuration. Secret-bearing values go through
services/secrets.get_secret(). Nothing is hard-coded, and every external value
has a safe default so the app boots on a laptop with no AWS account.

In production (APP_ENV=prod) the defaults are not safe, and the app refuses to
start on any of them: see production_problems() at the end of this file.
`.env.example` documents every setting for development, and
`.env.production.example` is the one production configuration.
"""

import os
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()

from app.services import secrets as _secrets  # noqa: E402  (needs dotenv first)
from app.services.secrets import get_secret  # noqa: E402

# --- Environment: "dev" or "prod". Nothing else: see _check_choices(). ---
APP_ENV = os.getenv("APP_ENV", "dev").strip().lower()
# Where secret-bearing settings come from: "env" or "secretsmanager".
SECRETS_BACKEND = _secrets.backend()

# --- Database ---
# Default targets a Homebrew Postgres on the host, authenticating as the OS
# user (no password). docker-compose overrides this with its own container URL.
DEFAULT_DATABASE_URL = "postgresql+psycopg://localhost:5432/step1"
DATABASE_URL = get_secret("DATABASE_URL", DEFAULT_DATABASE_URL)
# Pool sizing. One task at 0.25 vCPU runs one worker; 5 + 10 overflow is
# plenty and stays far under db.t4g.micro's ~80-connection ceiling.
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
# Seconds. A security group that drops packets makes connects hang for the OS
# TCP timeout (minutes); fail in seconds so the request gets a clean 503.
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))

# How long /health waits for the database before reporting it unreachable.
# The load balancer gives a health check a few seconds in all; an answer that
# arrives after that is a failed check however it reads. Well under
# DB_CONNECT_TIMEOUT on purpose: a request can wait ten seconds for a
# connection, a health check cannot.
HEALTH_DB_TIMEOUT_S = float(os.getenv("HEALTH_DB_TIMEOUT_S", "2"))

# --- Auth mode: "local" (bcrypt + our HS256 tokens) or "cognito" ---
AUTH_MODE = os.getenv("AUTH_MODE", "local").strip().lower()

# The default is public: it is in this file, in the repository. Anyone who
# has read it can sign a token for any user id. It exists so the app runs on
# a laptop with no setup, and production refuses to start with it (below).
DEFAULT_JWT_SECRET = "dev-secret-change-me-in-production"
JWT_SECRET = get_secret("JWT_SECRET", DEFAULT_JWT_SECRET)
# HS256 is only as strong as its key. Shorter than this and the key, not the
# algorithm, is what an attacker goes after.
JWT_SECRET_MIN_LENGTH = 32
JWT_ALGORITHM = "HS256"
# 12h. Long enough that a student isn't logged out mid-application-spree,
# short enough that a leaked token from a shared lab machine dies overnight.
JWT_EXPIRY_MINUTES = int(os.getenv("JWT_EXPIRY_MINUTES", "720"))

# bcrypt work factor: each step doubles the cost of one guess. 12 is ~0.25 s
# per hash on a laptop, which a login never notices and an offline attacker
# multiplies by every candidate password. Below 10 a stolen table falls to a
# GPU in days; above 14 a sign-in takes over a second and the endpoint becomes
# its own denial of service. The test suite lowers it, since it registers
# hundreds of throwaway accounts.
BCRYPT_ROUNDS = int(os.getenv("BCRYPT_ROUNDS", "12"))

# Passwords shorter than this are rejected at /auth/register. bcrypt ignores
# bytes past 72, so there is no useful upper bound to enforce beyond that.
PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "8"))

# --- Rate limits ---
# On by default. The test suite turns it off, except for the tests of the
# limits themselves: a suite that registers hundreds of accounts from one
# address would otherwise be refused by the thing it is testing.
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
# "<count>/<period>", per client address. Sign-in is the one that matters:
# at 10 a minute, working through a list of the 10,000 most common passwords
# takes most of a day from one address, against 40 minutes unthrottled. Much
# lower and a student who has forgotten which password they used is locked
# out by their own attempts.
LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "10/minute")
# Nobody registers five times in an hour by accident.
REGISTER_RATE_LIMIT = os.getenv("REGISTER_RATE_LIMIT", "5/hour")
# Deleting an account asks for the password, which makes it a second place
# to guess one.
DELETE_ACCOUNT_RATE_LIMIT = os.getenv("DELETE_ACCOUNT_RATE_LIMIT", "5/hour")
# Public and cached for five minutes by whoever asks; this is for whoever
# does not honour the cache.
STATS_RATE_LIMIT = os.getenv("STATS_RATE_LIMIT", "60/minute")

# --- Amazon Cognito (only used when AUTH_MODE=cognito) ---
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
COGNITO_USER_POOL_ID = get_secret("COGNITO_USER_POOL_ID", "").strip()
COGNITO_APP_CLIENT_ID = get_secret("COGNITO_APP_CLIENT_ID", "").strip()
# What the pool puts in every token's `iss`. Derived, never configured: a
# token is only as trustworthy as the issuer it is checked against.
COGNITO_ISSUER = (
    f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"
    if COGNITO_USER_POOL_ID
    else ""
)
# Where the pool's public signing keys are read from. By default the pool's
# own well-known URL. Two alternatives, for a task that cannot reach it:
#   COGNITO_JWKS_PATH  a file holding the same JSON, shipped with the task.
#                      Takes precedence. The keys are public, so the file is
#                      not a secret; it does have to be refreshed if the pool
#                      ever rotates its keys.
#   COGNITO_JWKS_URL   another URL serving it, such as a VPC endpoint.
COGNITO_JWKS_URL = os.getenv("COGNITO_JWKS_URL", "").strip() or (
    f"{COGNITO_ISSUER}/.well-known/jwks.json" if COGNITO_ISSUER else ""
)
COGNITO_JWKS_PATH = os.getenv("COGNITO_JWKS_PATH", "").strip()
# Seconds to wait for the keys. Every request with a token waits behind the
# first fetch, so this is also the longest a cold start can stall sign-in.
COGNITO_JWKS_TIMEOUT_S = float(os.getenv("COGNITO_JWKS_TIMEOUT_S", "5"))

# --- CORS: the frontend origin(s), comma-separated ---
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",") if o.strip()
]

# --- Behind a proxy ---
# Whether to believe X-Forwarded-For and X-Forwarded-Proto. They are ordinary
# request headers: anyone can send them. Behind a proxy that overwrites or
# appends to them (App Runner, an ALB, CloudFront) they are the only way to
# learn the real client address and scheme. With no proxy, believing them lets
# a client choose its own address, and with it a fresh rate limit for every
# request. So: false on a laptop, true behind the load balancer.
TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() == "true"
# How many proxies stand between the internet and this process. Each appends
# the address it saw to X-Forwarded-For, so the client's is this many from
# the right; everything further left was supplied by the client and means
# nothing. An Application Load Balancer in front of the task is 1.
# CloudFront in front of that load balancer would make it 2.
# Too low and everyone shares the proxy's address and one rate limit; too
# high and the client is choosing its own address again.
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "1"))

# Absolute base URL of this API as the BROWSER sees it. Local-mode presigned
# upload URLs are built from it, so behind a proxy or in compose it must be the
# externally reachable address, not the container's bind address.
PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE", "http://localhost:8000").rstrip("/")

# --- File storage: "local" filesystem or "s3" ---
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").strip().lower()
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "data/uploads")
S3_BUCKET = os.getenv("S3_BUCKET", "").strip()
KMS_KEY_ID = os.getenv("KMS_KEY_ID", "").strip()
# For an S3-compatible store that is not S3: a local stand-in under test, or
# MinIO. Unset in production, where the SDK finds S3 by region.
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "").strip()
# Presigned PUTs expire fast: the browser uses the URL immediately, and a
# resume URL that lingers in history is a PII leak with a timer on it.
PRESIGN_EXPIRY_SECONDS = int(os.getenv("PRESIGN_EXPIRY_SECONDS", "300"))
# 5 MB. A one-page text resume is ~100 KB; anything near this cap is a scan,
# and scans need OCR we don't run yet anyway.
RESUME_MAX_BYTES = int(os.getenv("RESUME_MAX_BYTES", str(5 * 1024 * 1024)))
# Below this many extracted characters the PDF is treated as image-only and
# flagged for OCR. A real one-page resume extracts to 2,000+ chars; 200 is
# "a name and an email", i.e. the text layer is missing.
RESUME_MIN_TEXT_CHARS = int(os.getenv("RESUME_MIN_TEXT_CHARS", "200"))

# How long a resume may take to parse before the attempt is abandoned. A real
# resume takes well under a second. This is for the file built to take hours.
RESUME_PARSE_TIMEOUT_S = float(os.getenv("RESUME_PARSE_TIMEOUT_S", "10"))

# --- Sources ---
# The Simplify repo name rolls forward every cycle (Summer2026- redirects to
# Summer2027-), so it's config, not a constant.
SIMPLIFY_REPO = os.getenv("SIMPLIFY_REPO", "SimplifyJobs/Summer2027-Internships")
VANSHB03_REPO = os.getenv("VANSHB03_REPO", "vanshb03/Summer2027-Internships")
SOURCE_BRANCH = os.getenv("SOURCE_BRANCH", "dev")
SOURCE_FETCH_TIMEOUT_S = float(os.getenv("SOURCE_FETCH_TIMEOUT_S", "60"))
# Backfill refuses to deactivate rows when a fetch returns fewer than this
# fraction of the currently-active set. A truncated or empty upstream file
# would otherwise mark the whole board closed in one run. 0 disables the guard.
DEACTIVATE_GUARD_RATIO = float(os.getenv("DEACTIVATE_GUARD_RATIO", "0.5"))

# --- Automatic refresh ---
# The API refreshes the listings itself: a background task checks each source
# and re-runs the backfill for any whose last successful run is older than
# INGEST_INTERVAL_HOURS. On by default in dev, where nothing else would do it.
# In production it has to be said out loud, either way: the recommended setup
# is AUTO_INGEST=true on the one always-on task, and the alternative is a
# scheduled job outside the API with this set to false. Left unset in prod it
# is off, so that nothing pulls twice by accident.
AUTO_INGEST = os.getenv("AUTO_INGEST", "true" if APP_ENV == "dev" else "false").lower() == "true"
# The upstream lists change through the day but a student checks daily. Much
# under 24 and every laptop running this re-downloads 12 MB for nothing; much
# over and "Posted today" has already been open for two days.
INGEST_INTERVAL_HOURS = float(os.getenv("INGEST_INTERVAL_HOURS", "24"))
# How often the task looks at the clock, and so how late a refresh can be and
# how soon a failed one is retried. The check itself is one small query.
INGEST_CHECK_MINUTES = float(os.getenv("INGEST_CHECK_MINUTES", "30"))
# When the process is told to stop, how long it waits for a refresh in
# progress to wind down and record itself as interrupted. ECS sends SIGTERM
# and then, after the task's stop timeout (30 seconds unless changed), kills
# the process. This and the server's own drain time must fit inside that.
INGEST_SHUTDOWN_GRACE_S = float(os.getenv("INGEST_SHUTDOWN_GRACE_S", "15"))

# --- Matching ---
# Postings older than this are hard-filtered out of the feed. Most intern reqs
# close within ~3 months; past 120 days the "active" flag upstream is usually
# stale rather than true.
POSTING_MAX_AGE_DAYS = int(os.getenv("POSTING_MAX_AGE_DAYS", "120"))

# Cached scores older than this are recomputed on the next read even if
# nothing else changed, because freshness decays daily. Much shorter and every
# page view rescoring; much longer and "Posted 3 days ago" is a week stale.
SCORES_MAX_AGE_HOURS = float(os.getenv("SCORES_MAX_AGE_HOURS", "24"))

# --- Application timeline ---
# applied|acknowledged with no company-side event for this long -> ghosted.
GHOST_AFTER_DAYS = int(os.getenv("GHOST_AFTER_DAYS", "30"))


def _check_rate_limits() -> None:
    """A mistyped limit should stop the app from starting, not silently
    leave a route unlimited or refuse every request to it."""
    from limits import parse

    for name in (
        "LOGIN_RATE_LIMIT",
        "REGISTER_RATE_LIMIT",
        "DELETE_ACCOUNT_RATE_LIMIT",
        "STATS_RATE_LIMIT",
    ):
        try:
            parse(globals()[name])
        except ValueError as exc:
            raise RuntimeError(
                f"{name}={globals()[name]!r} is not a rate limit. Use '<count>/<period>', "
                "for example 10/minute."
            ) from exc


def _check_choices() -> None:
    """Settings that take one of a few words. A misspelling must not fall
    through to a default: APP_ENV=production would otherwise run as dev, with
    every production check skipped, and AUTH_MODE=cognit as local auth."""
    for name, value, allowed in (
        ("APP_ENV", APP_ENV, ("dev", "prod")),
        ("AUTH_MODE", AUTH_MODE, ("local", "cognito")),
        ("STORAGE_BACKEND", STORAGE_BACKEND, ("local", "s3")),
        ("SECRETS_BACKEND", SECRETS_BACKEND, ("env", "secretsmanager")),
    ):
        if value not in allowed:
            raise RuntimeError(
                f"{name}={value!r} is not one of {', '.join(allowed)}. Refusing to guess."
            )


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", ""}
_TLS_MODES = {"require", "verify-ca", "verify-full"}


def _is_placeholder(value: str) -> bool:
    """Whether a value is one of the stand-ins from .env.production.example.
    They are published with the code, so a secret left as one is no secret."""
    return "CHANGE-ME" in value or "<" in value or ">" in value


def _origin_problem(name: str, value: str) -> str | None:
    """Why `value` is not a usable public https origin, or None if it is."""
    try:
        parts = urlsplit(value)
    except ValueError:
        return f"{name} contains {value!r}, which is not a URL."
    if parts.scheme != "https":
        return (
            f"{name} contains {value!r}, which is not https. Browsers reach production "
            "over https only."
        )
    if (parts.hostname or "") in _LOCAL_HOSTS:
        return f"{name} contains {value!r}, which points at this machine."
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return f"{name} contains {value!r}. Give the origin only: https://host, with no path."
    return None


def _database_problems(database_url: str) -> list[str]:
    # Nothing here may quote the URL: it carries the password.
    if not database_url.strip():
        return ["DATABASE_URL is not set."]
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import ArgumentError

    try:
        url = make_url(database_url)
    except ArgumentError:
        return ["DATABASE_URL could not be read as a database URL."]
    problems = []
    if not url.drivername.startswith("postgresql"):
        problems.append(
            f"DATABASE_URL uses the driver {url.drivername!r}; this app needs postgresql+psycopg."
        )
    if database_url == DEFAULT_DATABASE_URL or (url.host or "") in _LOCAL_HOSTS:
        problems.append(
            "DATABASE_URL points at this machine. In a container that is the container "
            "itself. Set it to the database's endpoint."
        )
    if not url.password:
        problems.append("DATABASE_URL has no password.")
    if url.query.get("sslmode") not in _TLS_MODES:
        problems.append(
            "DATABASE_URL does not require TLS, so the password and every row could "
            "cross the network in the clear. Add ?sslmode=require to the end of it."
        )
    return problems


def production_problems(
    *,
    auth_mode: str,
    jwt_secret: str,
    bcrypt_rounds: int,
    allowed_origins: list[str],
    database_url: str,
    public_api_base: str,
    storage_backend: str,
    s3_bucket: str,
    cognito_user_pool_id: str,
    cognito_app_client_id: str,
    cognito_jwks_url: str,
    cognito_jwks_path: str,
    aws_region: str,
    auto_ingest_set: bool,
) -> list[str]:
    """Settings that are fine on a laptop and must not reach production.

    Each is a way in or a way to lose data, not a preference, so the app does
    not start with any of them. Every message begins with the name of the
    variable to change. Returned rather than raised, so that all are reported
    at once and a deploy is not a game of one error at a time.
    """
    # Anything copied from the example and not filled in gets one message,
    # and none of the checks below, which would only describe the
    # placeholder. Values are never quoted: one stands where a password goes.
    named = {
        "DATABASE_URL": database_url,
        "JWT_SECRET": jwt_secret if auth_mode == "local" else "",
        "COGNITO_USER_POOL_ID": cognito_user_pool_id if auth_mode == "cognito" else "",
        "COGNITO_APP_CLIENT_ID": cognito_app_client_id if auth_mode == "cognito" else "",
        "ALLOWED_ORIGINS": ",".join(allowed_origins),
        "PUBLIC_API_BASE": public_api_base,
        "S3_BUCKET": s3_bucket if storage_backend == "s3" else "",
    }
    unfilled = {name for name, value in named.items() if _is_placeholder(value)}
    problems: list[str] = []

    def check(name: str, found: list[str]) -> None:
        if name in unfilled:
            found = [
                f"{name} still holds the placeholder from .env.production.example. "
                "Replace it with the real value."
            ]
        problems.extend(found)

    check("DATABASE_URL", _database_problems(database_url))

    if auth_mode == "local":
        secret = []
        if jwt_secret == DEFAULT_JWT_SECRET:
            secret.append(
                "JWT_SECRET is the development default, which is public. Anyone could "
                "sign in as anyone. Set JWT_SECRET to a long random value, for example "
                "the output of: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
            )
        elif len(jwt_secret) < JWT_SECRET_MIN_LENGTH:
            secret.append(
                f"JWT_SECRET is {len(jwt_secret)} characters; it must be at least "
                f"{JWT_SECRET_MIN_LENGTH}."
            )
        check("JWT_SECRET", secret)
        if bcrypt_rounds < 10:
            problems.append(
                f"BCRYPT_ROUNDS is {bcrypt_rounds}; below 10, stolen password hashes "
                "can be cracked in days."
            )
    elif auth_mode == "cognito":
        pool = []
        if not cognito_user_pool_id:
            pool.append(
                "COGNITO_USER_POOL_ID is not set, and AUTH_MODE is cognito. Without it "
                "no token can be checked."
            )
        elif not cognito_user_pool_id.startswith(f"{aws_region}_"):
            pool.append(
                f"COGNITO_USER_POOL_ID does not begin with {aws_region}_, the region in "
                "AWS_REGION. A pool's id starts with its region; one of the two is wrong, "
                "and tokens would be checked against an issuer that does not exist."
            )
        check("COGNITO_USER_POOL_ID", pool)
        client = []
        if not cognito_app_client_id:
            client.append(
                "COGNITO_APP_CLIENT_ID is not set, and AUTH_MODE is cognito. Without it "
                "a token issued to any other app in the pool would be accepted."
            )
        check("COGNITO_APP_CLIENT_ID", client)
        if not cognito_jwks_path and cognito_jwks_url:
            if urlsplit(cognito_jwks_url).scheme != "https":
                problems.append(
                    "COGNITO_JWKS_URL is not https. The signing keys decide who is "
                    "signed in; they are not fetched over a connection anyone can alter."
                )

    origins = []
    if not allowed_origins:
        origins.append(
            "ALLOWED_ORIGINS is empty. Set it to the frontend's origin, or no browser "
            "can call the API."
        )
    for origin in allowed_origins:
        if origin == "*":
            origins.append(
                "ALLOWED_ORIGINS contains '*'. With credentials allowed, that lets any "
                "website act as a signed-in user. List the frontend's origin instead."
            )
        elif problem := _origin_problem("ALLOWED_ORIGINS", origin):
            origins.append(problem)
    check("ALLOWED_ORIGINS", origins)

    if not public_api_base:
        base = ["PUBLIC_API_BASE is not set. Set it to the API's public https URL."]
    else:
        problem = _origin_problem("PUBLIC_API_BASE", public_api_base)
        base = [problem] if problem else []
    check("PUBLIC_API_BASE", base)

    if storage_backend == "s3":
        bucket = []
        if not s3_bucket:
            bucket.append(
                "S3_BUCKET is not set, and STORAGE_BACKEND is s3. There is nowhere to put a resume."
            )
        check("S3_BUCKET", bucket)

    if not auto_ingest_set:
        problems.append(
            "AUTO_INGEST is not set. Say which: true, and this service refreshes the "
            "listings itself every day; or false, and something else must. Unset, the "
            "listings would silently never refresh."
        )
    return problems


def _check_jwks_file() -> None:
    """A keys file that is missing or empty should stop the start, not the
    first person to sign in."""
    if AUTH_MODE != "cognito" or not COGNITO_JWKS_PATH:
        return
    import json

    try:
        with open(COGNITO_JWKS_PATH, encoding="utf-8") as f:
            keys = json.load(f)["keys"]
        if not isinstance(keys, list) or not keys:
            raise ValueError("no keys")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"COGNITO_JWKS_PATH={COGNITO_JWKS_PATH!r} could not be used ({type(exc).__name__}). "
            'It must be a readable JSON file of the form {"keys": [...]}, as served at the '
            "pool's /.well-known/jwks.json."
        ) from exc


def _check_production() -> None:
    if APP_ENV != "prod":
        return
    problems = production_problems(
        auth_mode=AUTH_MODE,
        jwt_secret=JWT_SECRET,
        bcrypt_rounds=BCRYPT_ROUNDS,
        allowed_origins=ALLOWED_ORIGINS if "ALLOWED_ORIGINS" in os.environ else [],
        database_url=DATABASE_URL,
        public_api_base=PUBLIC_API_BASE if "PUBLIC_API_BASE" in os.environ else "",
        storage_backend=STORAGE_BACKEND,
        s3_bucket=S3_BUCKET,
        cognito_user_pool_id=COGNITO_USER_POOL_ID,
        cognito_app_client_id=COGNITO_APP_CLIENT_ID,
        cognito_jwks_url=COGNITO_JWKS_URL,
        cognito_jwks_path=COGNITO_JWKS_PATH,
        aws_region=AWS_REGION,
        auto_ingest_set="AUTO_INGEST" in os.environ,
    )
    if problems:
        raise RuntimeError("Refusing to start with APP_ENV=prod:\n  - " + "\n  - ".join(problems))
    # Not fatal, but each changes what a protection actually does.
    import logging

    log = logging.getLogger(__name__)
    if not TRUST_PROXY:
        log.warning(
            "TRUST_PROXY is false in production. Behind a load balancer every request "
            "appears to come from the load balancer, so all clients share one rate limit."
        )
    if STORAGE_BACKEND == "local":
        log.warning(
            "STORAGE_BACKEND is local in production. Resumes are written to the "
            "container's disk, unencrypted, and lost when it is replaced."
        )
    if AUTH_MODE == "local" and not RATE_LIMIT_ENABLED:
        log.warning("RATE_LIMIT_ENABLED is false in production: sign-in is not throttled.")


_check_choices()
_check_rate_limits()
_check_jwks_file()
_check_production()
