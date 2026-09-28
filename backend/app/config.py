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

# --- Matching ---
# Postings older than this are hard-filtered out of the feed. Most intern reqs
# close within ~3 months; past 120 days the "active" flag upstream is usually
# stale rather than true.
POSTING_MAX_AGE_DAYS = int(os.getenv("POSTING_MAX_AGE_DAYS", "120"))

# --- Application timeline ---
# applied|acknowledged with no company-side event for this long -> ghosted.
GHOST_AFTER_DAYS = int(os.getenv("GHOST_AFTER_DAYS", "30"))
