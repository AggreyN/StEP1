# StEP1 backend

FastAPI + PostgreSQL. Internship postings from two public lists, classified
into roles, scored against a student's profile, with an application tracker.

Runs entirely on a laptop: local auth, local resume storage, no AWS account.
The design is in [`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md).

## Quick start (Homebrew PostgreSQL)

Needs Python 3.12+ and PostgreSQL 16.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # runtime deps plus tests and lint
                                                 # (requirements.txt alone runs the API)

createdb step1
createdb step1_test                       # only needed to run the tests

.venv/bin/alembic upgrade head            # create the schema
.venv/bin/python -m app.sources.backfill  # pull ~17,000 postings (about 15 seconds)
.venv/bin/uvicorn app.main:app --reload --port 8000
```

The backfill line is optional: the API pulls the listings itself the first
time it starts and keeps them fresh after that. See
[Keeping the listings fresh](#keeping-the-listings-fresh).

Then open <http://localhost:8000/docs>, or:

```bash
curl http://localhost:8000/health
# {"status":"ok","db":"ok"}
```

With no `.env` the app connects to `postgresql+psycopg://localhost:5432/step1`
as your OS user, which is how Homebrew's Postgres is set up by default. To
change anything, `cp .env.example .env` and edit.

## Quick start (Docker)

```bash
cd backend
docker compose up --build                                # Postgres 16 + the API
docker compose exec api python -m app.sources.backfill   # in a second terminal
curl http://localhost:8000/health
```

The container runs `alembic upgrade head` before it starts serving. Compose
publishes its Postgres on host port **5433** so it does not collide with a
Homebrew Postgres on 5432.

## Create an account

There is no seeded user. Register one:

```bash
curl -X POST http://localhost:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@umd.edu","password":"at-least-8-chars","display_name":"You"}'
```

The response carries `access_token`. Send it as `Authorization: Bearer <token>`
on every other request. `POST /auth/login` with the same email and password
returns a fresh token; tokens last 12 hours.

A new account has no profile. `GET /feed` answers `409 Complete onboarding
first` until `PUT /profile` has been called once:

```bash
TOKEN=...   # from the register response
curl -X PUT http://localhost:8000/profile \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{
    "school": "University of Maryland, College Park",
    "major": "Information Science",
    "degree_level": "Bachelor'"'"'s",
    "grad_year": 2028,
    "target_terms": ["Summer 2027"],
    "preferred_locations": ["Washington, DC"],
    "remote_ok": true,
    "interests": [
      {"role": "software", "rank": 1},
      {"role": "ai_ml_data", "rank": 2},
      {"role": "data_analytics", "rank": 3}
    ]
  }'
curl "http://localhost:8000/feed?page_size=5" -H "Authorization: Bearer $TOKEN"
```

## Commands

| What | Command |
|---|---|
| Run the API | `.venv/bin/uvicorn app.main:app --reload --port 8000` |
| Apply migrations | `.venv/bin/alembic upgrade head` |
| Refresh every source now | `.venv/bin/python -m app.sources.backfill` |
| Refresh one source now | `.venv/bin/python -m app.sources.backfill --source=simplify` (or `vanshb03`) |
| Mark silent applications ghosted | `.venv/bin/python -m app.jobs.ghost` |
| Tests | `.venv/bin/pytest` |
| Lint | `.venv/bin/ruff check . && .venv/bin/ruff format --check .` |

### Keeping the listings fresh

**The API refreshes the listings by itself, once a day.** There is nothing to
schedule.

While the API is running, a background task looks at the `ingest_runs` table
when the server starts and every 30 minutes after. Any source whose last
*successful* run is more than 24 hours old is pulled again, using the same
code as the command below. It runs in a worker thread, so the API keeps
answering while it works (a refresh takes about three seconds).

What that means in practice:

- **A laptop that was off overnight catches up when you start the server.**
  The first check happens at startup.
- **Restarting does not reset anything.** The decision comes from the table,
  not from a timer, so `--reload` restarting the server all afternoon does not
  cause extra pulls or delay the next one.
- **A failed pull is retried at the next check,** 30 minutes later, not the
  next day. The failure is recorded with its error, and the postings already
  stored are left exactly as they were.
- **Only one refresh runs at a time,** across processes. Every refresh holds
  a Postgres advisory lock; a second server or worker that finds it taken
  skips that round.

**To check how fresh the data is,** ask the API (any signed-in user):

```bash
curl http://localhost:8000/ingest/status -H "Authorization: Bearer $TOKEN"
```

```jsonc
{ "last_success_at": "2026-09-29T02:42:53.164496Z",  // every source is at least this fresh
  "next_due_at":     "2026-09-30T02:42:53.164496Z",  // last_success_at + the interval
  "interval_hours": 24,
  "auto": true,              // AUTO_INGEST
  "running": false,          // a refresh is in progress right now, in any process
  "active_postings": 4769,
  "sources": [
    { "source": "simplify", "last_success_at": "...", "last_attempt_at": "...",
      "fetched": 16914, "upserted": 86, "deactivated": 0,
      "error": null }        // the last attempt's error, if it failed
  ] }
```

`last_success_at` is the oldest of the sources' last successes. If
`next_due_at` is in the past, a refresh is overdue: either the API was not
running, or the last attempts failed, in which case the source's `error` says
why. `fetched`, `upserted` and `deactivated` describe the last attempt.

Or look at the table directly:

```sql
SELECT source, fetched, upserted, deactivated, error, finished_at
  FROM ingest_runs ORDER BY id DESC LIMIT 4;
```

**To force a refresh now,** run the backfill. It ignores the 24 hours and
pulls immediately:

```bash
.venv/bin/python -m app.sources.backfill                     # every source
.venv/bin/python -m app.sources.backfill --source=simplify   # one source
docker compose exec api python -m app.sources.backfill       # under Docker
```

This is safe while the API is running. It takes the same lock, so if an
automatic refresh is in progress it waits for that to finish first. Feeds pick
up the new postings on their next request, and the next automatic refresh is
due 24 hours after this one.

**To change or turn off the schedule,** set these in `.env`:

| Variable | Default | Purpose |
|---|---|---|
| `AUTO_INGEST` | `true` when `APP_ENV=dev`, otherwise `false` | `false` turns automatic refresh off; the listings then change only when you run the backfill |
| `INGEST_INTERVAL_HOURS` | `24` | How old a source's last success may be before it is pulled again |
| `INGEST_CHECK_MINUTES` | `30` | How often the API looks. Also how late a refresh can be, and how soon a failed one is retried |

Automatic refresh is off by default outside development because the
production design pulls from a scheduled Lambda (§1 of the architecture
document) and the API should not also be pulling. Set `AUTO_INGEST=true` to
have the API do it there too.

Each run writes one JSON log line, whoever started it:

```json
{"message": "ingest finished", "source": "simplify", "fetched": 16914, "inserted": 18,
 "updated": 68, "unchanged": 16828, "upserted": 86, "deactivated": 0,
 "duration_ms": 2902, "error": null}
```

### What a refresh does

Safe to run as often as you like. It upserts on `(source, source_id)`, skips
rows whose content hash is unchanged, marks rows that dropped out of a list as
inactive, and writes one `ingest_runs` row per source:

```sql
SELECT source, fetched, upserted, deactivated, error, finished_at
  FROM ingest_runs ORDER BY id DESC LIMIT 4;
```

A second run straight after the first reports `upserted = 0`. Nothing is
filtered at ingest: closed and hidden postings are stored and excluded when
the feed is read.

If a fetch fails, the error is recorded and nothing is deactivated. If a fetch
returns less than half of what is currently open, deactivation is skipped for
that run (`DEACTIVATE_GUARD_RATIO`), so a truncated upstream file cannot close
the whole board. Neither counts as a successful run, so both are retried at
the next check.

If the process is stopped partway through a refresh, the transaction is rolled
back and the run is left without a finish time. The next refresh marks it
`Interrupted before it finished.` and carries on.

The Simplify repository is renamed every recruiting cycle. When the backfill
starts failing with a 404, update `SIMPLIFY_REPO`.

### Tests

The suite needs a real PostgreSQL, because the schema uses arrays, JSONB, a
generated `tsvector` column and `pg_trgm`. By default it uses
`postgresql+psycopg://localhost:5432/step1_test`; set `TEST_DATABASE_URL` to
point it elsewhere. It rebuilds that database's schema from the migration on
every run and truncates the tables between tests, so **never point it at a
database you care about**.

```bash
createdb step1_test
.venv/bin/pytest
```

CI (`.github/workflows/backend-tests.yml`) runs ruff and pytest against a
`postgres:16` service container on every push that touches `backend/`.

## Environment variables

Every variable is read in `app/config.py` and documented in `.env.example`.
All have defaults. The ones you are likely to touch:

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://localhost:5432/step1` | Postgres connection |
| `TEST_DATABASE_URL` | `postgresql+psycopg://localhost:5432/step1_test` | Database the tests rebuild |
| `AUTH_MODE` | `local` | `local` (bcrypt + HS256) or `cognito` |
| `JWT_SECRET` | dev placeholder | Signs local tokens. With `APP_ENV=prod` the app will not start on the placeholder, or on anything under 32 characters |
| `BCRYPT_ROUNDS` | `12` | Cost of hashing a password |
| `RATE_LIMIT_ENABLED` | `true` | Rate limits on sign-in, registration, account deletion and `/stats` |
| `LOGIN_RATE_LIMIT` | `10/minute` | Per client address |
| `REGISTER_RATE_LIMIT` | `5/hour` | Per client address |
| `DELETE_ACCOUNT_RATE_LIMIT` | `5/hour` | Per client address |
| `STATS_RATE_LIMIT` | `60/minute` | Per client address |
| `TRUST_PROXY` | `false` | Believe `X-Forwarded-For` and `X-Forwarded-Proto`. **Set `true` on App Runner, and only behind a proxy** |
| `TRUSTED_PROXY_HOPS` | `1` | Proxies between the internet and the API. App Runner alone is 1 |
| `JWT_EXPIRY_MINUTES` | `720` | Token lifetime |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | CORS origins, comma-separated |
| `PUBLIC_API_BASE` | `http://localhost:8000` | This API's URL as the browser sees it; used to build local upload URLs |
| `STORAGE_BACKEND` | `local` | `local` (files under `UPLOAD_DIR`) or `s3` |
| `UPLOAD_DIR` | `data/uploads` | Where local resumes are written |
| `RESUME_MAX_BYTES` | `5242880` | Resume size cap (5 MB) |
| `RESUME_PARSE_TIMEOUT_S` | `10` | Seconds a resume may take to parse before the attempt is abandoned |
| `PRESIGN_EXPIRY_SECONDS` | `300` | How long an upload link is valid |
| `SIMPLIFY_REPO` | `SimplifyJobs/Summer2027-Internships` | Rolls forward each cycle |
| `VANSHB03_REPO` | `vanshb03/Summer2027-Internships` | Secondary list |
| `AUTO_INGEST` | `true` in dev | Refresh the listings automatically |
| `INGEST_INTERVAL_HOURS` | `24` | How often each source is refreshed |
| `INGEST_CHECK_MINUTES` | `30` | How often the API checks whether a refresh is due |
| `POSTING_MAX_AGE_DAYS` | `120` | Older postings are left out of the feed |
| `SCORES_MAX_AGE_HOURS` | `24` | Cached scores older than this are recomputed |
| `GHOST_AFTER_DAYS` | `30` | Silence before an application is marked ghosted |
| `APP_ENV` | `dev` | `prod` reads secrets from AWS Secrets Manager first |

Secret-bearing values (`DATABASE_URL`, `JWT_SECRET`, the Cognito ids) go
through `services/secrets.get_secret()`: the environment in development, AWS
Secrets Manager under `<SECRETS_PREFIX>/<NAME>` when `APP_ENV=prod`.

`AUTH_MODE=cognito` and `STORAGE_BACKEND=s3` are written but have never been
run against AWS. Treat them as untested.

## API

Interactive documentation is at `/docs` in development. It and
`/openapi.json` do not exist when `APP_ENV=prod`. Errors are always
`{"detail": "a readable sentence"}`, including validation errors, rate limits
and crashes. Every timestamp is UTC to the second: `2026-09-29T02:42:53Z`.

```
GET    /health                                               public
GET    /stats                    -> the board in numbers     public

POST   /auth/register            POST /auth/login            public, rate limited
GET    /me                       DELETE /me                  -> delete the account

GET    /profile                  PUT  /profile               -> 202 + Retry-After
POST   /profile/resume/presign   -> an upload slot
PUT    /profile/resume/local/{key}   (local storage only)    -> 204
POST   /profile/resume/commit    -> extracted skills

GET    /feed?page=&page_size=&sort=&roles=&location=&term=&min_score=&remote=
GET    /feed/status
GET    /postings/{id}
GET    /ingest/status            -> how fresh the listings are

GET    /saved                    POST /saved/{id}            DELETE /saved/{id}

GET    /applications             POST /applications
GET    /applications/{id}        POST /applications/{id}/events
```

A posting's id is `"{source}:{source_id}"`, for example
`simplify:2909b23b-d049-4f31-9d5e-a71faacba4af`. URL-encode the colon or not;
both work.

### `GET /stats`

Public: no token. For the About page.

```jsonc
{ "active_postings": 4769,     // open and visible
  "companies": 1241,           // distinct companies with at least one of those
  "role_families": 15,         // roles the classifier knows, "other" included
  "updated_at": "2026-09-29T02:42:53Z" }   // same value as /ingest/status last_success_at; null before the first refresh
```

Counts of the shared board and nothing about any user, so the response is the
same for everyone and is sent with `Cache-Control: public, max-age=300`.
Limited to 60 requests a minute per address.

### `DELETE /me`

Deletes the caller's account and everything stored about them.

```bash
curl -X DELETE http://localhost:8000/me \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"password": "the-account-password"}'
```

| Response | When |
|---|---|
| `204` | Deleted |
| `403` `Password is incorrect.` | The password did not match. Nothing was deleted |
| `422` `password: Field required` | No password was sent |
| `429` | More than 5 attempts in an hour from this address |

What goes: the user, the profile and ranked interests, the stored resume and
its extracted text, any upload in progress, cached scores, saved postings,
applications and their whole event history, contacts, drafted messages, and
connected integrations. The rows go in one transaction; then the files are
removed from storage. Nothing is kept, anonymised or soft-deleted.

Afterwards the token answers `401`, and the email address can register again
as a new, empty account.

The password is asked for again so that a token left signed in on a shared
machine is not enough to destroy an account. With `AUTH_MODE=cognito` no
password is sent: the pool checked it to issue the token. Deleting here
removes what this service holds. The user's record in the Cognito pool is
separate and has to be deleted there.

### Uploading a resume

Three calls. The browser sends the file itself to `upload_url`; in production
that is S3 and the API never handles the bytes.

```jsonc
// 1. POST /profile/resume/presign
{ "filename": "My Resume.pdf", "content_type": "application/pdf", "size": 71973 }
// -> 200
{ "upload_url": "http://localhost:8000/profile/resume/local/resumes/3/4a13...b3.pdf",
  "key": "resumes/3/4a136b2ffae14776a24a71b87d3734b3.pdf",
  "method": "PUT",
  "headers": { "Content-Type": "application/pdf", "Content-Length": "71973" } }

// 2. PUT <upload_url>, body = the file, with those headers.
//    Local storage also wants the bearer token. S3 must not be sent one.
// -> 204 (local) or 200 (S3)

// 3. POST /profile/resume/commit
{ "key": "resumes/3/4a136b2ffae14776a24a71b87d3734b3.pdf", "filename": "My Resume.pdf" }
// -> 200
{ "filename": "My Resume.pdf", "uploaded_at": "2026-09-29T04:30:03Z",
  "skills": ["Python", "SQL"], "needs_ocr": false }
```

`size` is the file's length in bytes (`file.size` in a browser). The upload is
then held to exactly that many bytes. A browser sets `Content-Length` itself
and ignores a script's attempt to; the header is listed for clients that are
not browsers.

| Refused with | When |
|---|---|
| `422` at presign | Not `application/pdf`, filename not `.pdf`, or `size` outside 1 KB to 5 MB |
| `404` `Unknown upload key.` | The key was never issued, was issued to someone else, or is not a key |
| `409` at PUT | The link has already been used |
| `410` at PUT | The link has expired (5 minutes) |
| `400` or `413` at PUT | The body is not exactly the declared size, or is over 5 MB |
| `400` `That file isn't a PDF.` at commit | The file's first bytes are not a PDF's, whatever it is called |
| `400` at commit | The PDF is password-protected, cannot be read, or took too long to read |

A file refused at commit is deleted from storage. Asking for a new upload link
discards the previous unfinished one. A scanned PDF with no text is accepted
with `needs_ocr: true` and no skills.

### Feed order

`GET /feed` takes `sort`:

| `sort` | Order |
|---|---|
| `recent` (default) | Newest first by date posted, undated postings last; then best score |
| `score` | Best score first; then newest |

Anything else is a 422. The filters, `page`, `page_size`, `total` and
`has_more` behave the same under both: `sort` changes the order of the same
set of postings and nothing else. Every posting still carries its score and
reasons under `recent`. `GET /saved` is always newest-saved first.

## How matching works

`app/services/matching.py`. The scoring is deterministic and every point can
be traced to a rule.

**Hard filters** remove a posting from the feed:

- it is closed or hidden upstream
- it was posted more than 120 days ago
- it declares degree levels and yours is not among them
- it declares terms and none is one of your target terms or the term next to one

**Score**, for what is left:

| Component | Weight | Rule |
|---|---|---|
| Field match | 30 | Your best-ranked interest among the posting's roles: rank 1 → 30, 2 → 24, 3 → 20, 4 → 16, 5 → 12 |
| Skills | 20 | Share of the skills named in the title that are on your resume |
| Location | 15 | Same metro 15, same state 10, remote (if you are open to it) 15 |
| Term | 15 | Exact target term 15, adjacent term 8 |
| Freshness | 10 | `10 * exp(-days_since_posted / 30)` |
| Company | 10 | You saved or applied to another role at this company |

**The score is out of what the posting could have earned.** A component is
left out of the total when it could not be earned at all: the posting lists no
terms, no locations, names no skill in its title, or has no date; or you gave
no preference for it. `score = round(100 * earned / earnable)`. Without this,
a list that omits terms would lose 15 points on every row for what it did not
say.

Each component that earns points adds a reason (`role_rank`, `skills`,
`location`, `term`, `fresh`, `company`) that the frontend shows as a chip.

Scores are cached in `match_scores` and recomputed when the profile changes,
when a refresh (automatic or manual) changes the board, or after 24 hours. Scoring the whole board
for one student is one SQL query and one Python pass, about 70 ms for 4,500
postings.

## Security

What each item on the hardening checklist comes to in this codebase, where it
is enforced, and the test that fails if it stops being true. Items the
checklist marks as not applying to this app (3, 4, 9, 12) are not listed.

| # | Item | Enforced in | Held by |
|---|---|---|---|
| 1 | Keys stay on the server | `config.py`, `services/secrets.py` | Nothing secret is sent to a browser; `test_responses.py` |
| 2 | No secrets in Git | `.github/workflows/security.yml` (gitleaks, whole history) | CI, every push |
| 5 | Encryption at rest | S3: every upload requests SSE (`storage.py`). RDS: **see below** | `test_resume.py` (S3 signed headers) |
| 6 | Auth on the server | `auth.py: current_user`, on every route but four | `test_authorization.py` lists the public routes by name |
| 7 | Records locked to their owner | Every query on a user's table filters by the caller; another user's object is a 404 | `test_authorization.py`, over every route |
| 8 | No field tampering | `schemas.py: RequestModel` refuses unknown fields; no route unpacks a body into a model | `test_field_tampering.py` |
| 10 | Passwords hashed | `auth.py`, bcrypt, cost 12 | `test_auth.py`, `test_production_config.py` |
| 11 | Sign-in rate limited | `ratelimit.py`, `middleware.py: client_ip` | `test_rate_limits.py`, `test_real_server.py` |
| 13 | Queries parameterized | No SQL is built from strings; `LIKE` patterns are escaped | `test_sql_safety.py` reads the source and attacks the API |
| 14 | Input bounded | `limits.py`, `schemas.py`, `middleware.py: BodyLimitMiddleware` | `test_bounds.py` |
| 15 | User content escaped | Rendering is the frontend's job (React escapes). The API stores text exactly as typed and returns it only as JSON, with `nosniff` and a policy under which nothing renders | `test_sql_safety.py`, `test_security_headers.py` |
| 16 | Uploads restricted | `routes/profile.py`, `services/storage.py`, `services/pdf_worker.py` | `test_resume.py` |
| 17 | Responses trimmed | `response_model=` on every route | `test_responses.py` |
| 18 | Security headers | `middleware.py: SecurityHeadersMiddleware` | `test_security_headers.py` |
| 19 | HTTPS | App Runner and Amplify serve nothing else; HSTS is sent | `test_security_headers.py` |
| 20 | Dependencies scanned | `security.yml` (pip-audit), `.github/dependabot.yml` | CI, every push and weekly |

Most of those tests are written to be exhaustive rather than thorough. They
walk the application's routes, tables or source and fail when something exists
that they do not cover. A new route has to be given an authorization case, a
response model and, if it takes a body, a tampering case before the suite will
pass.

### Before deploying

Three things cannot be done in code, or cannot be done later.

**Turn on RDS storage encryption when the instance is created.** It is a
checkbox at creation (`--storage-encrypted` in the CLI) and cannot be switched
on afterwards: encrypting an existing instance means snapshotting it, copying
the snapshot with encryption, and restoring to a new instance. This database
holds resumes' text and application histories. Do it first.

**Set a real `JWT_SECRET`.** The default is in this repository, so anyone can
sign a token for any user with it. With `APP_ENV=prod` and local auth the app
refuses to start on the default, or on a secret shorter than 32 characters,
and says so:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

It also refuses `BCRYPT_ROUNDS` below 10 and `*` in `ALLOWED_ORIGINS`.

**Set `TRUST_PROXY=true` on App Runner.** App Runner's load balancer connects
to the container, so without it every request appears to come from one
address and all clients share a single rate limit: ten sign-ins a minute for
everyone together. With it, the client's address is read from
`X-Forwarded-For`, counting `TRUSTED_PROXY_HOPS` entries from the right. App
Runner alone is 1. If CloudFront is put in front, it is 2. Entries further
left were sent by the client and are never used.

Leave it `false` anywhere there is no proxy. There the header is whatever the
client chose to send.

### Rate limits

| Route | Limit | Refusal |
|---|---|---|
| `POST /auth/login` | 10 a minute | `Too many sign-in attempts. Try again in a minute.` |
| `POST /auth/register` | 5 an hour | `Too many accounts created from here. Try again in about an hour.` |
| `DELETE /me` | 5 an hour | `Too many attempts to delete an account. Try again in about an hour.` |
| `GET /stats` | 60 a minute | `Too many requests. Try again in a minute.` |

Per client address, on a sliding window. A refusal is a `429` with a
`Retry-After` header in seconds. Once the limit is reached the right password
is refused like any other.

**The counters are in the process's memory.** That is correct for one
instance. It means:

- A restart clears them. Under `uvicorn --reload`, saving a file resets every
  limit.
- With more than one instance, each keeps its own count, so the effective
  limit is the configured one multiplied by the number of instances. Before
  scaling past one, give the limiter a shared store: add `limits[redis]` to
  `requirements.txt` and change `storage_uri` in `app/ratelimit.py` to
  `redis://...`. Nothing else changes.

**Run uvicorn with `--no-proxy-headers`** where you control the command; the
container does. By default uvicorn replaces the client's address with the one
in `X-Forwarded-For` for any connection from the local machine, before the app
sees the request. The app detects an address that could have come from the
header and does not use it, so the limit cannot be reset by sending one. But
such requests share a second allowance, so the ceiling from a trusted host is
twice the configured limit. With the flag it is exactly the limit.

### Uploads

The resume upload is the one place a stranger hands the API a file. What it
says about that file is either pinned in advance or ignored.

- **The storage key is generated on the server**, from the user's id and a
  random UUID: `resumes/3/4a13...b3.pdf`. Nothing the client sent is in it.
  The file's name is kept in the database, to show back, with paths and
  control characters removed.
- **The upload link is for one file.** S3 URLs are signed (SigV4) with
  `content-type`, `content-length` and the encryption header among the signed
  headers, and expire after 5 minutes. A different type or length fails the
  signature. The local route enforces the same, counting bytes as they arrive
  rather than trusting `Content-Length`, and takes one upload per link.
- **Commit looks at the file, not the claim.** The stored object's real size
  is compared with what was declared, then its first five bytes are read. Only
  if they are `%PDF-` is the rest fetched and a parser started.
- **Parsing is isolated.** It runs in a child process with an empty
  environment, a 10-page cap, a 100,000-character cap and a 10-second
  deadline. A PDF built to hang is killed; one that crashes the parser takes
  the child with it and nothing else. Either is a `400`.
- **Nothing serves a resume back.** There is no download route. If one is
  added it must be a short-lived presigned `GET` with
  `ResponseContentDisposition=attachment`, after checking the caller owns the
  key; never the file's bytes through this API. A test fails if a route under
  `/profile/resume` answers `GET`.
- **Replacing a resume deletes the previous file**, and deleting an account
  deletes all of them.

PDF only. The checklist would allow `.docx`; one format means one parser to
trust. The size floor is 1 KB rather than the suggested 25 KB, which would
refuse plain one-page resumes exported as text.

### Headers

On every response, including errors, refusals and routes that do not exist:

```
X-Content-Type-Options: nosniff
Referrer-Policy: strict-origin-when-cross-origin
X-Frame-Options: DENY
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
Cache-Control: no-store                 (unless the route sets its own; /stats does)
Strict-Transport-Security: max-age=31536000; includeSubDomains
                                        (over HTTPS, and always when APP_ENV=prod)
```

The policy is the strictest there is because this is a JSON API: nothing it
returns should be rendered or framed. The frontend's own policy is set
separately, where the pages are served. In development `/docs` alone gets a
looser policy, enough for Swagger UI.

### Scanning

```bash
# What CI runs, locally
gitleaks git --redact .
pip-audit -r backend/requirements.txt
pip-audit -r backend/requirements-dev.txt
```

Dependabot opens pull requests weekly for `backend/requirements.txt`,
`backend/requirements-dev.txt`, `frontend/package.json` and the GitHub
Actions. `bcrypt` is held below 4.1
until passlib can use it.

## Where this differs from the architecture document

The document is the specification. These are the places it was silent,
contradicted itself, or could not be implemented as written.

| Document | What the code does | Why |
|---|---|---|
| §2.6 (role taxonomy) is referenced but not in the document | `app/sources/roles.py` is the taxonomy: 14 roles plus `other` | It is the validated classifier |
| §3 `postings.category`, `profile_interests.category` | `postings.category` keeps the source's raw category; `postings.roles TEXT[]` holds the classifier output; `profile_interests` stores `role` | The API contract and the matcher work in roles |
| §3 omits `is_visible` | `postings.is_visible` added | §4 filters on it |
| §3 `search_tsv` is generated from `company_name` | `postings.company_name` added alongside `company_id` | A generated column cannot read another table |
| §3 has no resume metadata | `profiles.resume_filename`, `resume_uploaded_at`, `resume_needs_ocr` | `GET /profile` returns them |
| §3 has no record of which profile version was scored | `profiles.scores_version`, `scores_computed_at` | "Ready" must be decidable even when no posting survives the filters |
| §4 rank points: "1 → 30, 2 → 24, … 5 → 12" | 30, 24, 20, 16, 12 | No constant step passes through all three stated values |
| §4 filter: terms must overlap target terms; §4 score: adjacent term → 8 | The filter admits exact and adjacent terms | An exact-overlap filter would remove every posting the 8 points are for |
| §4 skills: Jaccard against `search_tsv` lexemes | Share of the skills named in the **title** that you have, matched by the same code that reads the resume | See below |
| §4 company: "or a repeat employer of UMD students" | Only "saved or applied to the same company" | There is no data for the second half |
| §4 reasons for every component | A reason only when the component earned points | The chips are reasons to apply |
| §5 `GET /feed?category=` | `?roles=` (comma-separated), plus `page_size`, `remote` and `sort` | Follows from roles replacing category; `sort` defaults to newest first |
| §1 ingest is a nightly Lambda | In development the API refreshes the listings itself every 24 hours | A laptop has no EventBridge; off by default outside development |
| §5 has no freshness endpoint | `GET /ingest/status` | So a student can see the data is current |
| §5 `presign` → `{ upload_url, key }` | Request also takes `size`; response also has `method` and `headers` | The upload is pinned to one type and one exact length |
| §5 has no way to delete an account | `DELETE /me` | The privacy page promises one |
| §5 has no public route | `GET /stats` | The About page states real numbers |
| Checklist 16: allow `.pdf` and `.docx`, 25 KB to 10 MB | PDF only, 1 KB to 5 MB | Stricter on type: one parser, one format to reason about. Lower on size: a plain one-page PDF is often under 25 KB |
| Checklist 18: CSP `default-src 'self'; ...` | `default-src 'none'; frame-ancestors 'none'` on the API | That policy is for pages. This is a JSON API and loads nothing |
| §6 diagram | `applied` may skip to `oa_sent` or `interview_scheduled`; `oa_completed` sits after `oa_sent`; `ghosted` can still move on a late reply | The diagram omits an event kind it lists, and companies skip steps |
| §2.2 vanshb03 has `season` instead of `terms` | The year is inferred from the posting date | A bare "Summer" cannot be compared with "Summer 2027" |

**Skills.** Three problems with the rule as written. Jaccard divides by the
union, so a student with 15 skills matching a posting that names one scores
1/15 of the weight, and listing more skills lowers every score. Stemmed
lexemes collapse C, C++ and C# into the single lexeme `c`. And `search_tsv`
includes the company name, so every posting at Snowflake or Oracle would
"ask for" that skill. The implemented rule has none of these problems. To
restore the literal rule, the change is confined to the skills block of
`score_posting()`.

Duplicate postings across the two lists are not collapsed; doing so would
change what a posting id means.

## Layout

```
app/
  main.py  config.py  database.py  models.py  schemas.py
  auth.py  deps.py  logging_config.py
  limits.py  middleware.py  ratelimit.py
  routes/    health auth profile feed postings saved applications ingest stats
  services/  secrets storage resume_parse pdf_worker locations terms matching
             feed_state postings timeline ingest_scheduler
  sources/   base roles github_list simplify vanshb03 backfill
  jobs/      ghost
alembic/versions/0001_initial_schema.py  0002_resume_uploads.py
tests/
```

## Data sources and credit

Postings come from two community-maintained lists. This project links out to
the original posting and does not present the data as its own.

- [SimplifyJobs / Pitt CSC Summer Internships](https://github.com/SimplifyJobs/Summer2027-Internships)
- [vanshb03 / Summer2027-Internships](https://github.com/vanshb03/Summer2027-Internships) (MIT)
