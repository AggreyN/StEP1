"""Environment-driven settings for the StEP1 backend.

The one place that reads configuration. Secret-bearing values go through
services/secrets.get_secret(): the environment in dev, AWS Secrets Manager in
prod (APP_ENV=prod). Nothing is hard-coded, and every external value has a
safe default so the app boots on a laptop with no AWS account. See
`.env.example` for the documented list.
"""

import os

from dotenv import load_dotenv

load_dotenv()

from app.services.secrets import get_secret  # noqa: E402  (needs dotenv first)

# --- Environment: "dev" reads .env; "prod" reads AWS Secrets Manager ---
APP_ENV = os.getenv("APP_ENV", "dev").lower()

# --- Database ---
# Default targets a Homebrew Postgres on the host, authenticating as the OS
# user (no password). docker-compose overrides this with its own container URL.
DATABASE_URL = get_secret("DATABASE_URL", "postgresql+psycopg://localhost:5432/step1")
# Pool sizing. App Runner at 0.25 vCPU runs one worker; 5 + 10 overflow is
# plenty and stays far under db.t4g.micro's ~80-connection ceiling.
DB_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
DB_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
# Seconds. A security group that drops packets makes connects hang for the OS
# TCP timeout (minutes); fail in seconds so the request gets a clean 503.
DB_CONNECT_TIMEOUT = int(os.getenv("DB_CONNECT_TIMEOUT", "10"))

# --- Auth mode: "local" (bcrypt + our HS256 tokens) or "cognito" ---
AUTH_MODE = os.getenv("AUTH_MODE", "local").lower()

JWT_SECRET = get_secret("JWT_SECRET", "dev-secret-change-me-in-production")
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

# --- Amazon Cognito (only used when AUTH_MODE=cognito; untested in v1) ---
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
COGNITO_USER_POOL_ID = get_secret("COGNITO_USER_POOL_ID", "")
COGNITO_APP_CLIENT_ID = get_secret("COGNITO_APP_CLIENT_ID", "")
COGNITO_ISSUER = (
    f"https://cognito-idp.{AWS_REGION}.amazonaws.com/{COGNITO_USER_POOL_ID}"
    if COGNITO_USER_POOL_ID
    else ""
)
COGNITO_JWKS_URL = f"{COGNITO_ISSUER}/.well-known/jwks.json" if COGNITO_ISSUER else ""

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
# request. So: false on a laptop, true on App Runner.
TRUST_PROXY = os.getenv("TRUST_PROXY", "false").lower() == "true"
# How many proxies stand between the internet and this process. Each appends
# the address it saw to X-Forwarded-For, so the client's is this many from
# the right; everything further left was supplied by the client and means
# nothing. App Runner alone is 1. CloudFront in front of App Runner is 2.
# Too low and everyone shares the proxy's address and one rate limit; too
# high and the client is choosing its own address again.
TRUSTED_PROXY_HOPS = int(os.getenv("TRUSTED_PROXY_HOPS", "1"))

# Absolute base URL of this API as the BROWSER sees it. Local-mode presigned
# upload URLs are built from it, so behind a proxy or in compose it must be the
# externally reachable address, not the container's bind address.
PUBLIC_API_BASE = os.getenv("PUBLIC_API_BASE", "http://localhost:8000").rstrip("/")

# --- File storage: "local" filesystem or "s3" ---
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").lower()
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "data/uploads")
S3_BUCKET = os.getenv("S3_BUCKET", "")
KMS_KEY_ID = os.getenv("KMS_KEY_ID", "")
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
# Off by default in prod, where the nightly ingest is a scheduled Lambda (§1)
# and the API should not also be pulling; set AUTO_INGEST=true to override.
AUTO_INGEST = os.getenv("AUTO_INGEST", "true" if APP_ENV == "dev" else "false").lower() == "true"
# The upstream lists change through the day but a student checks daily. Much
# under 24 and every laptop running this re-downloads 12 MB for nothing; much
# over and "Posted today" has already been open for two days.
INGEST_INTERVAL_HOURS = float(os.getenv("INGEST_INTERVAL_HOURS", "24"))
# How often the task looks at the clock, and so how late a refresh can be and
# how soon a failed one is retried. The check itself is one small query.
INGEST_CHECK_MINUTES = float(os.getenv("INGEST_CHECK_MINUTES", "30"))

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
