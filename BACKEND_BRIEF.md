# Claude Code brief — `backend` branch

Paste this whole file as your first message in Claude Code, with
`docs/ARCHITECTURE.md` open in the repo.

---

You are working on **StEP1**, an internship discovery and application tracker.
The full design is in `docs/ARCHITECTURE.md` in this repo — **read it before
writing any code**, especially §2 (data sources), §2.6 (role taxonomy), §3
(schema), §4 (matching), and §5 (API surface). It is the spec. Where this
brief and the doc disagree, the doc wins; tell me about the conflict.

## Branch setup

```bash
git checkout main
git checkout -b backend
```

All work on `backend`. Do not touch `frontend/` — a parallel branch owns it.

## Scope of this brief

Steps 1–6 of §12 in the architecture doc. When you finish, a developer should
be able to clone the repo, run `docker compose up`, run one backfill command,
and have a locally queryable board of ~4,100 classified internship postings
with working auth, profiles, and a scored feed.

**Do not build**: the frontend, Cognito wiring, Bedrock calls, Gmail, GitHub
OAuth, outreach, or anything that requires an AWS account. `AUTH_MODE=local`
and `STORAGE_BACKEND=local` are the only modes that need to work.

## Conventions — non-negotiable

These come from `github.com/AggreyN/Rackner-Project`, which is the same
author's prior work. Match them:

- **`app/config.py` is the only place that reads the environment.** Every
  secret-bearing value goes through `services/secrets.get_secret(name,
  default)` — reads env in dev, AWS Secrets Manager when `APP_ENV=prod`.
  Nothing is hard-coded, and every external key has a safe default so the app
  boots with no AWS account.
- **`AUTH_MODE` switch.** `local` = bcrypt + HS256 tokens we sign;
  `cognito` = validate the pool's RS256 JWT against its JWKS. `current_user`
  is the single dependency routes use and does the right thing for either.
  Build the `cognito` branch of the code now but leave it untested and
  unconfigured.
- **One router module per domain** in `app/routes/`, mounted in `main.py`.
- **SQLAlchemy 2.0 `Mapped[]` style**, Alembic for every schema change.
- **Comments explain *why*, not *what*.** Where a constant is tuned, say what
  breaks at other values. The Rackner `config.py` is the reference for tone.
- Structured JSON access logging middleware with a request id, CloudWatch-ready.

## Deliverables

### 1 · Skeleton

```
backend/
├── Dockerfile                 # python:3.12-slim, uvicorn, non-root user
├── docker-compose.yml         # postgres:16 + the api, for local dev
├── requirements.txt
├── alembic.ini
├── pytest.ini
├── .env.example               # every var in config.py, documented
└── app/
    ├── main.py  config.py  database.py  models.py  schemas.py
    ├── auth.py  deps.py  logging_config.py
    ├── routes/     health.py auth.py profile.py feed.py postings.py saved.py
    ├── services/   secrets.py storage.py matching.py resume_parse.py
    └── sources/    base.py roles.py simplify.py vanshb03.py backfill.py
```

`GET /health` returns `{"status":"ok","db":"ok"}` and is the first thing that
works. CI (`.github/workflows/backend-tests.yml`) runs ruff + pytest on push.

### 2 · Models + migrations

Implement §3 of the doc exactly. Every table, every index, every unique
constraint. One Alembic revision, `initial schema`.

Two details people get wrong, so be explicit:

- `postings.search_tsv` is a **generated column**:
  `to_tsvector('english', title || ' ' || coalesce(company_name,''))`, with a
  GIN index.
- `applications.status` is **derived** from the newest row in
  `application_events`. Write a `recompute_status(application)` helper called
  on every event insert. Never let a caller set `status` directly.

### 3 · Local auth

`POST /auth/register`, `POST /auth/login`, `GET /me`. bcrypt via passlib,
HS256 tokens. Pin `bcrypt<4.1` — passlib 1.7.4's backend probe raises on 4.1+
and every `hash_password()` call dies. (This bit the Rackner build; the pin is
in its `requirements.txt` with the same comment.)

### 4 · Sources and the classifier

`app/sources/roles.py` **already exists and is validated** — 0.17%
unclassified across 4,139 real postings. Do not rewrite it. Use
`classify(title, category) -> list[str]`.

`sources/base.py` defines `NormalizedPosting` (§2.5) and an abstract
`Source.fetch() -> Iterable[NormalizedPosting]`. Then:

- `simplify.py` — fetch
  `https://raw.githubusercontent.com/{SIMPLIFY_REPO}/dev/.github/scripts/listings.json`.
  `SIMPLIFY_REPO` is an env var (default `SimplifyJobs/Summer2027-Internships`)
  because **the repo name rolls forward every cycle**.
- `vanshb03.py` — same path shape, different repo. It has no `category` and
  uses `season` instead of `terms`; normalize both.
- `backfill.py` — `python -m app.sources.backfill [--source=all]`. Idempotent:
  upsert on `(source, source_id)`, skip the UPDATE when `content_hash` is
  unchanged, mark rows absent from the feed as `active=false`, and write one
  `ingest_runs` row per source with counts.

**Filter to `active AND is_visible` on read, not on ingest.** Keep inactive
rows — they're how you show "this closed 3 days ago" later.

### 5 · Profile + resume

`GET/PUT /profile`, and `profile_interests` as a ranked list of 1–5 roles from
the `roles.py` enum. `PUT /profile` bumps `profile_version`.

`POST /profile/resume/presign` → a presigned S3 PUT. In `STORAGE_BACKEND=local`
mode, return a URL to a local `PUT /profile/resume/local/{key}` endpoint that
writes to `UPLOAD_DIR`, so the whole upload flow is exercisable with no AWS.
`services/storage.py` hides which backend is active behind one interface.

`POST /profile/resume/commit` extracts text with **PyMuPDF** and pulls skills
by matching against a curated skill list in `services/resume_parse.py` — a
plain list of ~200 terms (languages, frameworks, cloud, data tools). No LLM, no
Textract in this brief. If extraction yields under 200 characters, flag
`resume_needs_ocr=true` and move on; don't fail the request.

### 6 · Matching and the feed

`services/matching.py` implements §4. Hard filters first, then the weighted
sum. Every component appends a `{code, label, detail}` object to `reasons`.

Scoring all active postings for one user must be **one SQL query plus a Python
pass**, not a query per posting. At ~4,100 rows it should finish in well under
a second — add a test that asserts it.

`GET /feed` returns cached `match_scores` rows, recomputing only when
`profile_version` differs. `GET /feed/status` returns
`{"state":"building"|"ready","pct":int}`; `PUT /profile` returns **202** with a
`Retry-After` header and kicks the rescore into a background task.

Set `expose_headers=["Retry-After"]` on the CORS middleware. Without it the
browser cannot read the header and the polling loop silently breaks.

## Shared response shapes — the contract

The `frontend` branch is being built in parallel against mock JSON in exactly
these shapes. **Do not change a field name without telling me**, because a
rename here is a broken merge there.

```jsonc
// GET /postings/{id}  — and each element of GET /feed .items
{
  "id": "simplify:2909b23b-...",
  "title": "Software Engineer Intern",
  "company": { "name": "Palantir", "url": "https://..." },
  "roles": ["solutions_architecture", "software"],
  "role_labels": ["Solutions & Sales Engineering", "Software Engineering"],
  "locations": ["Washington, DC"], "is_remote": false,
  "terms": ["Summer 2027"], "degrees": ["Bachelor's"],
  "url": "https://job-boards.greenhouse.io/...",
  "date_posted": "2026-09-02T00:00:00Z",
  "salary": { "min": 60, "max": null, "unit": "hour" },
  "source": "simplify",
  "score": 87,
  "reasons": [
    { "code": "role_rank", "label": "Matches your #1 field", "detail": "Solutions & Sales Engineering" },
    { "code": "skills",    "label": "2 of your skills",      "detail": "Python, SQL" },
    { "code": "fresh",     "label": "Posted 3 days ago",     "detail": null }
  ],
  "saved": false,
  "application": null          // or { "id": 12, "status": "applied" }
}

// GET /feed
{ "items": [ ...postings... ], "page": 1, "total": 412, "has_more": true }

// GET /feed/status
{ "state": "building", "pct": 40, "step": "Scanning 4,139 open internships" }

// GET /profile
{ "school": "University of Maryland, College Park", "major": "Information Science",
  "minor": "Data Science", "degree_level": "Bachelor's", "grad_year": 2028,
  "gpa": 3.7, "target_terms": ["Summer 2027"],
  "preferred_locations": ["Washington, DC", "New York, NY"], "remote_ok": true,
  "interests": [ { "role": "software", "label": "Software Engineering", "rank": 1 } ],
  "resume": { "filename": "resume.pdf", "uploaded_at": "...", "skills": ["Python"] },
  "profile_version": 3 }

// GET /applications/{id}
{ "id": 12, "posting": { ...posting... }, "status": "interview_scheduled",
  "applied_at": "2026-09-01T...",
  "events": [ { "id": 40, "kind": "applied", "occurred_at": "...", "note": null, "source": "manual" } ],
  "next_transitions": ["interviewed", "rejected", "withdrawn"] }

// Errors, everywhere
{ "detail": "human-readable message" }
```

`next_transitions` is computed server-side from the state machine in §6 — the
frontend renders buttons from it and does not hard-code the graph.

## Acceptance — how I'll check

1. `docker compose up` → `GET /health` returns `{"status":"ok","db":"ok"}`.
2. `alembic upgrade head` from empty creates every table in §3.
3. `python -m app.sources.backfill` → **at least 3,500 active postings**, and
   the role distribution roughly matches the §2.6 table (software ~58%,
   `other` under 1%).
4. Running backfill twice changes no rows the second time, and writes a second
   `ingest_runs` row showing `upserted≈0`.
5. Register → login → `PUT /profile` with 3 ranked roles → poll `/feed/status`
   → `GET /feed` returns scored, sorted results with populated `reasons`.
6. `pytest` passes. Minimum coverage: the classifier against a fixture of ~30
   real titles, the scorer's component weights, the derived-status helper, and
   backfill idempotency.
7. No AWS credentials needed for any of the above.

## Working style

- Commit per deliverable with a real message, not one giant commit.
- If §3 or §5 of the doc is wrong or underspecified, **say so and propose a
  fix** rather than quietly inventing something.
- Do not add dependencies beyond what the deliverables need. No Celery, no
  Redis, no ORM-adjacent magic — `BackgroundTasks` is sufficient for the
  rescore at this scale.
- Stop when acceptance passes. Do not start on Cognito, Bedrock, or the
  frontend.
