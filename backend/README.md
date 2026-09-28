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
.venv/bin/pip install -r requirements.txt

createdb step1
createdb step1_test                       # only needed to run the tests

.venv/bin/alembic upgrade head            # create the schema
.venv/bin/python -m app.sources.backfill  # pull ~17,000 postings (about 15 seconds)
.venv/bin/uvicorn app.main:app --reload --port 8000
```

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
| Backfill every source | `.venv/bin/python -m app.sources.backfill` |
| Backfill one source | `.venv/bin/python -m app.sources.backfill --source=simplify` (or `vanshb03`) |
| Mark silent applications ghosted | `.venv/bin/python -m app.jobs.ghost` |
| Tests | `.venv/bin/pytest` |
| Lint | `.venv/bin/ruff check . && .venv/bin/ruff format --check .` |

### Backfill

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
the whole board.

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
| `JWT_SECRET` | dev placeholder | Signs local tokens. **Change it outside development.** |
| `JWT_EXPIRY_MINUTES` | `720` | Token lifetime |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | CORS origins, comma-separated |
| `PUBLIC_API_BASE` | `http://localhost:8000` | This API's URL as the browser sees it; used to build local upload URLs |
| `STORAGE_BACKEND` | `local` | `local` (files under `UPLOAD_DIR`) or `s3` |
| `UPLOAD_DIR` | `data/uploads` | Where local resumes are written |
| `RESUME_MAX_BYTES` | `5242880` | Resume size cap (5 MB) |
| `SIMPLIFY_REPO` | `SimplifyJobs/Summer2027-Internships` | Rolls forward each cycle |
| `VANSHB03_REPO` | `vanshb03/Summer2027-Internships` | Secondary list |
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

Interactive documentation is at `/docs`. Errors are always
`{"detail": "a readable sentence"}`, including validation errors.

```
GET    /health

POST   /auth/register            POST /auth/login            GET /me

GET    /profile                  PUT  /profile               -> 202 + Retry-After
POST   /profile/resume/presign   -> where to upload
PUT    /profile/resume/local/{key}   (local storage only)
POST   /profile/resume/commit    -> extracted skills

GET    /feed?page=&page_size=&roles=&location=&term=&min_score=&remote=
GET    /feed/status
GET    /postings/{id}

GET    /saved                    POST /saved/{id}            DELETE /saved/{id}

GET    /applications             POST /applications
GET    /applications/{id}        POST /applications/{id}/events
```

A posting's id is `"{source}:{source_id}"`, for example
`simplify:2909b23b-d049-4f31-9d5e-a71faacba4af`. URL-encode the colon or not;
both work.

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
when a backfill changes the board, or after 24 hours. Scoring the whole board
for one student is one SQL query and one Python pass, about 70 ms for 4,500
postings.

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
| §5 `GET /feed?category=` | `?roles=` (comma-separated), plus `page_size` and `remote` | Follows from roles replacing category |
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
  routes/    health auth profile feed postings saved applications
  services/  secrets storage resume_parse locations matching
             feed_state postings timeline
  sources/   base roles github_list simplify vanshb03 backfill
  jobs/      ghost
alembic/versions/0001_initial_schema.py
tests/
```

## Data sources and credit

Postings come from two community-maintained lists. This project links out to
the original posting and does not present the data as its own.

- [SimplifyJobs / Pitt CSC Summer Internships](https://github.com/SimplifyJobs/Summer2027-Internships)
- [vanshb03 / Summer2027-Internships](https://github.com/vanshb03/Summer2027-Internships) (MIT)
