# StEP1

Internship discovery and application tracking for students.

StEP1 pulls internship postings from public GitHub lists, classifies them
into roles, and scores each one against a student's profile (school, major,
graduation year, target terms, locations, and resume). Students save
postings, track applications through a timeline (applied, interview,
offer, rejected, ghosted), and get a personalized feed that refreshes as new
postings come in.

The backend is FastAPI and PostgreSQL. The frontend is Next.js, TypeScript,
and Tailwind. Both run entirely on a laptop, with local accounts and local
resume storage: no AWS account is needed to develop or demo the app.

## Run it locally

Needs Python 3.12+, Node, and PostgreSQL 16.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

createdb step1
.venv/bin/alembic upgrade head
.venv/bin/python -m app.sources.backfill   # pull postings, about 15 seconds
.venv/bin/uvicorn app.main:app --reload --port 8000
```

```bash
cd frontend
npm install
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev   # http://localhost:3000
```

The frontend can also run against an in-memory mock with no backend at all:
`NEXT_PUBLIC_API_BASE=mock npm run dev`. See `frontend/README.md`.

The backend refreshes its postings by itself once a day; the command above
just makes the first run faster. See `backend/README.md` for the full list
of environment variables, the API surface, and how sign-in, resume upload,
and rate limits work.

## Tests

```bash
cd backend && .venv/bin/pytest && .venv/bin/ruff check . && .venv/bin/ruff format --check .
cd frontend && npm test && npm run lint && npm run typecheck
```

The backend suite needs a real PostgreSQL database (`createdb step1_test`);
it never touches `step1`. The frontend suite runs against the mock API by
default.

## Documentation

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): the design document. Data
  sources, database schema, matching, the API surface, and the reasoning
  behind each infrastructure choice.
- [`AWS_SETUP.md`](AWS_SETUP.md): the account-level and console steps a
  production deployment needs that can't be scripted; not needed to run the
  app locally.
- [`backend/README.md`](backend/README.md) and
  [`frontend/README.md`](frontend/README.md): commands, environment
  variables, and where each side differs from the architecture document.

## Data sources

Postings come from two public lists maintained on GitHub:
[`SimplifyJobs/Summer2027-Internships`](https://github.com/SimplifyJobs/Summer2027-Internships)
(the Simplify list, originally started by Pitt CSC) and
[`vanshb03/Summer2027-Internships`](https://github.com/vanshb03/Summer2027-Internships).
The vanshb03 repository is MIT licensed. SimplifyJobs ships no license file,
so its data is not redistributed as StEP1's own: every posting links back to
its original listing, and credit for the underlying lists belongs to their
maintainers, not to this project.
