# StEP1 — Architecture

_Internship discovery and application tracking for students._
_Target repo: `github.com/AggreyN/StEP1` · Author: Aggrey Narh · Drafted 2026-09-14_

This is the design document. No code yet — the point is to settle the service
map, the schema, and the four or five decisions that are expensive to change
later, before anything gets built.

Conventions follow the Rackner FDI backend (`AUTH_MODE` switch, `get_secret()`
indirection, `app/routes/` per domain, cached per-user scores) so the two
projects read as one body of work.

---

## 0 · TL;DR

| Layer | Choice | Why |
|---|---|---|
| Frontend | Next.js + TypeScript + Tailwind, static-exported onto **Amplify Hosting** | Client-rendered, so no SSR server is needed; `amplify.yml` carries over almost verbatim |
| Auth | **Cognito User Pool** (Essentials tier), JWT validated against JWKS | Reuses `app/auth.py` from Rackner nearly line-for-line |
| API | **FastAPI** in a container on **ECS Express Mode** (Fargate) | App Runner is closed to new customers from 30 April 2026; Express Mode is AWS's own replacement path. See §1 |
| Database | **RDS PostgreSQL** `db.t4g.micro` | Predictable ~$14/mo; `pg_trgm` + `tsvector` do the matching |
| Resumes | **S3**, private, presigned PUT | Browser uploads straight to S3; the API never touches the bytes |
| Ingestion | **In-process scheduler** inside the API, once a day | `AUTO_INGEST=true`; no separate compute to pay for or keep patched. EventBridge + Lambda remain the answer once ingestion needs to run somewhere other than the API. Pulls the GitHub lists into `postings` |
| AI | **Bedrock**, narrowly | Match *explanations* and outreach drafts only — scoring itself is deterministic |

Estimated fixed cost: **~$52–55/month**. See §10 — this is higher than the
original estimate below because Express Mode's Application Load Balancer and
three public IPv4 addresses cost more than App Runner ever did, and App
Runner is no longer an option for a service created after this document.

Three things in the original brief need correcting before you build on them —
LinkedIn, Indeed, and Gmail. See [§9 Reality checks](#9--reality-checks). Read
that section first; it changes what §5 and §7 can promise.

---

## 1 · Service map

```
                    ┌──────────────────────────────┐
  Browser  ────────▶│  Amplify Hosting (static)     │
                    └───────┬──────────────┬───────┘
                            │              │
              JWT (Cognito) │              │ presigned PUT
                            ▼              ▼
                    ┌───────────────┐   ┌──────────────┐
                    │  ALB          │   │  S3          │
                    │  (Express     │   │  resumes/    │
                    │   Mode)       │   └──────▲───────┘
                    └───────┬───────┘          │
                            ▼                  │
                    ┌───────────────┐          │
                    │  Fargate task │──────────┘
                    │  FastAPI      │
                    └───┬───────┬───┘
                        │       │
        ┌───────────────┘       └────────────┐
        ▼                                    ▼
┌────────────────┐                  ┌──────────────────┐
│ RDS PostgreSQL │                  │ Bedrock          │
│  postings      │                  │  explain + draft │
│  profiles      │                  └──────────────────┘
│  applications  │
└───────▲────────┘
        │ upsert, once a day
        │ (in-process scheduler; no separate compute)
        └── SimplifyJobs · vanshb03
```

**Cognito** owns passwords. The API never sees one — it validates the
pool-issued RS256 JWT against the public JWKS and upserts a `users` row keyed
by the token's `sub`. This is exactly `app/auth.py` in Rackner, and the
`AUTH_MODE=local` bcrypt fallback comes with it, so the whole app runs on a
laptop with no AWS account wired up. Keep that. It is the single biggest
reason the Rackner backend stayed demoable.

**ECS Express Mode, not App Runner.** This document originally chose App
Runner over hand-rolled ECS + an Application Load Balancer, for the reasons
in the paragraph below, which are all still true. But App Runner is **closed
to new customers from 30 April 2026** (AWS, *App Runner service
availability change*), so a service created after that date cannot use it at
all, and AWS's own migration guidance for a new service is Express Mode —
a thinner layer over the same Fargate + ALB pair, built and updated with one
API call instead of the dozen resources ECS otherwise asks for by hand. It
creates a cluster, a task definition, a service with canary deployments and
alarm-based rollback, the ALB itself (HTTPS listener, target group, security
groups), autoscaling, a log group, and a metric alarm — as one unit, torn
down as one unit. Same `Dockerfile`, same `uvicorn` command as before; only
what runs it changed. The concrete steps are in `AWS_SETUP.md` §2.6.

The reasoning behind the original choice, for the record: App Runner gave
you HTTPS, a public URL, auto-deploy from ECR, and autoscaling with no load
balancer to pay for, at roughly $2.52/month idle versus Rackner's hand-rolled
ECS + ALB at roughly $38/month before a single request arrived — the ALB
alone was about $20 of that. Express Mode still puts an ALB in front of the
service, so it does not recover App Runner's price; see §10 for what it
actually costs now.

The alternative is Lambda + Mangum behind a Function URL, which is
free-tier-to-near-zero but adds cold starts on a page whose whole selling
point is a fast first dashboard. Express Mode over bare Lambda for the same
reason App Runner was chosen originally; the container is portable if you
change your mind.

---

## 2 · Data sources

Four sources, three of which are genuinely usable. Verified by cloning each
repo on 2026-09-14.

### 2.1 SimplifyJobs / Pitt CSC — primary

`github.com/SimplifyJobs/Summer2027-Internships` → `.github/scripts/listings.json`

**16,578 listings, 3,768 currently active-and-visible, 1,018 distinct
companies.** One flat JSON array, one object per posting:

```json
{
  "source": "Simplify",
  "category": "AI/ML/Data",
  "company_name": "Samsung Research America",
  "id": "2909b23b-d049-4f31-9d5e-a71faacba4af",
  "title": "2026 Intern - Computer Vision & ML - Summer",
  "active": false,
  "terms": ["Summer 2026"],
  "date_updated": 1768692260,
  "date_posted": 1768692260,
  "url": "https://job-boards.greenhouse.io/...",
  "locations": ["Mountain View, CA"],
  "company_url": "https://simplify.jobs/c/Samsung-Research-America",
  "is_visible": true,
  "sponsorship": "Other",
  "degrees": ["Master's", "PhD"]
}
```

Field distributions, which matter because they define what the onboarding form
can actually ask for:

| Field | Values |
|---|---|
| `category` | AI/ML/Data (6909), Software (5114), Hardware (2752), Product (1058), Quant (532) — plus a long-form variant set (`Software Engineering`, `Data Science, AI & Machine Learning`, …) used by the newer rows |
| `terms` | Summer 2026 (8465), Fall 2026 (2904), Summer 2027 (2401), N/A (1644), Winter 2026, Spring 2026, Winter 2027, … |
| `degrees` | Bachelor's (11416), Master's (5368), PhD (2407), MBA, Associate's, … |
| `sponsorship` | Other (16472), Does Not Offer Sponsorship (57), U.S. Citizenship Required (26), Offers Sponsorship (23) |

Two traps. **The category vocabulary is not normalized** — `Software` and
`Software Engineering` are both live, as are `AI/ML/Data` and
`Data Science, AI & Machine Learning`. Map both spellings to one canonical
enum at ingest. And **`sponsorship` is 99% `"Other"`**, so it is useless as a
filter; do not build a work-authorization filter on it.

The repo URL rolls forward each cycle (`Summer2026-` now redirects to
`Summer2027-`). Put the repo slug in an env var, not a constant.

### 2.2 vanshb03 / Summer2027-Internships — secondary

Same `.github/scripts/listings.json` path, **471 listings / 371 active**, same
field names minus `category` and `degrees`, plus `season` (`"Winter"`) instead
of `terms`. MIT licensed. Small but it surfaces off-cycle and startup roles
Simplify misses. Cheap to add: one extra normalizer function.

### 2.3 speedyapply / 2026-SWE-College-Jobs — optional, later

No JSON in the repo — the listings live in a Supabase instance and only the
rendered markdown tables are committed. You'd have to parse HTML-in-markdown
table rows. **The reason to bother is salary**: it is the only one of the three
that publishes rates (`$60/hr`, `$62/hr`). Defer to v1.5, and if you do it,
parse `README.md` (intern USA) and `INTERN_INTL.md` only.

### 2.4 Adzuna + USAJobs — breadth beyond CS

- **Adzuna**: `GET https://api.adzuna.com/v1/api/jobs/us/search/1?app_id=…&app_key=…`.
  Free app_id/app_key on signup, JSON. Use it to cover non-CS majors — the
  GitHub lists are tech-only, and if this is going to serve all of ColorStack
  and not just the CS side, you need it. Check the current rate limit and the
  caching/attribution terms on the developer portal before you cache results
  in your own DB.
- **USAJobs**: `GET https://data.usajobs.gov/api/Search?HiringPath=student`.
  Free API key; three headers required — `Host: data.usajobs.gov`,
  `User-Agent: <the email you registered>`, and `Authorization-Key: <key>`.
  `HiringPath=student` / `graduates` is exactly the federal intern
  pipeline (Pathways), and it is a real differentiator — nobody's GitHub list
  covers NIST, NSA, NASA, or the census. Very relevant at a Maryland school.

Both go behind the same `Source` interface as the GitHub lists, and both
degrade to a clean 503 if their key is unset — the Rackner `SAM_GOV_API_KEY`
pattern.

### 2.5 Normalized posting record

Every source normalizes into one shape before it touches the DB:

```python
NormalizedPosting(
    source: str,            # "simplify" | "vanshb03" | "adzuna" | "usajobs"
    source_id: str,         # stable id from that source
    company_name: str,
    title: str,
    category: Category,     # canonical enum, mapped from source vocabulary
    locations: list[str],
    is_remote: bool,
    terms: list[str],       # "Summer 2027"
    degrees: list[str],
    url: str,
    date_posted: datetime,
    date_updated: datetime,
    active: bool,
    salary_min: Decimal | None,
    salary_max: Decimal | None,
    salary_unit: str | None,   # "hour" | "year"
    raw: dict,              # the untouched source object, JSONB
)
```

Keeping `raw` costs a few hundred MB at this volume and means a schema mistake
is a re-backfill, not a re-scrape.

---

## 3 · Database schema

PostgreSQL 16, SQLAlchemy 2.0 `Mapped[]` style, Alembic migrations —
same as Rackner.

```
users                 id, cognito_sub, email, password_hash(local mode only),
                      display_name, created_at

profiles              user_id PK/FK, school, major, minor, degree_level,
                      grad_year, gpa, target_terms[], preferred_locations[],
                      remote_ok, work_auth, resume_s3_key, resume_text,
                      resume_skills[], onboarded_at, profile_version

profile_interests     user_id, category, rank (1..5)      ← the "3–5 fields"
                      UNIQUE(user_id, rank)

companies             id, name, normalized_name UNIQUE, url

postings              id, source, source_id, company_id FK, title,
                      category, locations[], is_remote, terms[], degrees[],
                      url, date_posted, date_updated, active,
                      salary_min, salary_max, salary_unit,
                      raw JSONB, content_hash,
                      search_tsv tsvector GENERATED,
                      first_seen_at, last_seen_at
                      UNIQUE(source, source_id)

match_scores          user_id, posting_id, score, reasons JSONB,
                      profile_version, computed_at
                      UNIQUE(user_id, posting_id)

saved_postings        user_id, posting_id, created_at
                      UNIQUE(user_id, posting_id)

applications          id, user_id, posting_id, status, applied_at,
                      last_event_at, created_at
                      UNIQUE(user_id, posting_id)

application_events    id, application_id, kind, occurred_at, note,
                      source ('manual' | 'gmail' | 'system'), created_at

contacts              id, user_id, application_id, name, role, email,
                      linkedin_url, created_at

outreach_messages     id, application_id, contact_id, channel, subject,
                      body, status, follow_up_due_at, sent_at

integrations          user_id, provider ('gmail'|'github'|'linkedin'),
                      external_id, scopes[], token_secret_arn,
                      connected_at, revoked_at

ingest_runs           id, source, started_at, finished_at,
                      fetched, upserted, deactivated, error
```

Four things worth defending:

**`profile_version`.** Bump it on every profile save. `match_scores` rows
carry the version they were computed under, so a profile edit invalidates the
cache by comparison instead of a `DELETE`. This is the `fit_estimates`
invalidation problem from Rackner, solved a little more cleanly.

**`application_events` is append-only, and `applications.status` is derived.**
Storing only a status column loses the history — and the history is the whole
point of the timeline UI. Status is recomputed from the newest event on write.

**`content_hash`.** SHA-256 of the fields that matter (title, url, locations,
terms, active). Ingest skips the `UPDATE` when it matches, which turns a
16,000-row nightly pull into a few dozen writes.

**`ingest_runs`.** Same idea as Rackner's `SearchFetch` freshness ledger: when
the feed looks stale you want to know whether last night's pull ran, not guess.

### Indexes

```sql
CREATE INDEX ON postings USING GIN (search_tsv);
CREATE INDEX ON postings USING GIN (locations);
CREATE INDEX ON postings (active, date_posted DESC);
CREATE INDEX ON postings (category, active);
CREATE INDEX ON match_scores (user_id, score DESC);
CREATE EXTENSION pg_trgm;   -- fuzzy company-name dedupe across sources
```

`pgvector` for semantic resume↔posting similarity is a v1.5 upgrade, not a v1
requirement. Ship the deterministic scorer first.

---

## 4 · Matching

**The scoring is deterministic. The LLM only explains it.** Two reasons: it
costs effectively nothing, and every number on screen can be traced to a rule —
which is the same "no unexplained scores" property that made the Rackner fit
panel defensible.

Hard filters first (these remove rows, they don't score them):

- `active = true AND is_visible = true`
- `degrees` overlaps the student's level, when the posting declares any
- `terms` overlaps the student's `target_terms`, when the posting declares any
- posting older than 120 days → dropped

Then a 0–100 weighted sum, each component emitting a reason string:

| Component | Weight | Rule |
|---|---|---|
| Field match | 30 | Interest rank 1 → 30, rank 2 → 24, … rank 5 → 12; unranked category → 0 |
| Skills overlap | 20 | Jaccard of `resume_skills` against the posting's `search_tsv` lexemes |
| Location | 15 | Exact metro → 15; same state → 10; remote and `remote_ok` → 15; else 0 |
| Term precision | 15 | Exact target term → 15; adjacent term → 8 |
| Freshness | 10 | `10 · exp(-days_since_posted / 30)` |
| Company signal | 10 | Saved/applied-to a peer company before, or a repeat employer of UMD students |

`reasons` is stored as JSONB and rendered as chips on the card —
`Matches your #1 field: AI/ML/Data` · `2 of your skills: PyTorch, SQL` ·
`Posted 3 days ago`. Bedrock is called **only** to turn those chips into one
sentence of prose, batched per page, cached per `(user, posting,
profile_version)`. Skip it entirely and the product still works.

**GPA should not affect matching.** You are collecting it, and you should keep
collecting it — it belongs in the resume and in outreach copy. But essentially
no posting in any of these sources declares a GPA cutoff, so a GPA-weighted
score would be inventing a signal. Use it in §7, not here.

---

## 5 · API surface

FastAPI, one router module per domain in `app/routes/`, mirroring Rackner.

```
GET    /health

GET    /me
GET    /profile
PUT    /profile                       → bumps profile_version, enqueues rescore
POST   /profile/resume/presign        → { upload_url, key }
POST   /profile/resume/commit         → { key } → parse + extract skills

GET    /feed?page=&category=&location=&term=&min_score=
GET    /feed/status                   → { state: "building"|"ready", pct }
GET    /postings/{id}

GET    /saved
POST   /saved/{posting_id}
DELETE /saved/{posting_id}

GET    /applications
POST   /applications                  → { posting_id } creates + 'applied' event
GET    /applications/{id}
POST   /applications/{id}/events      → { kind, occurred_at, note }

GET    /applications/{id}/contacts
POST   /applications/{id}/contacts
POST   /applications/{id}/outreach/draft
GET    /outreach/due                  → follow-ups owed today

GET    /integrations
GET    /integrations/{provider}/authorize
GET    /integrations/{provider}/callback
DELETE /integrations/{provider}
```

### The "starting your career…" screen

Make it real work, not a timer. On the first `PUT /profile`:

1. API writes the profile, bumps `profile_version`, returns **202** with a
   `Retry-After` header.
2. A background task parses the resume (PyMuPDF text → Textract only if the
   PDF is image-only — the Rackner `OCR_MODE` pattern) and scores the student
   against every active posting.
3. Frontend polls `GET /feed/status` and shows real substeps:
   _Reading your resume → Scanning 3,768 open internships → Ranking your
   matches_.
4. `ready` → route to the dashboard.

Scoring 3,768 rows is a single SQL pass plus a Python loop — well under a
second. The screen will be honest and brief, which is better than a fake
three-second delay.

Set `expose_headers=["Retry-After"]` on the CORS middleware or the browser
can't read the poll hint. You hit this exact bug in Rackner.

---

## 6 · Application timeline

The states, derived from the event log:

```
 saved
   └─▶ applied ──▶ acknowledged ──▶ oa_sent ──▶ interview_scheduled
                                                      │
                                                      ▼
                                                 interviewed
                                                  │        │
                                    additional_round      offer ──▶ accepted
                                                  │        │
                                                  └────────┴──▶ rejected
 any state ──▶ withdrawn
 applied|acknowledged, 30d silent ──▶ ghosted   (nightly system event)
```

Event kinds: `applied`, `acknowledged`, `oa_sent`, `oa_completed`,
`interview_scheduled`, `interviewed`, `additional_round`, `offer`, `accepted`,
`rejected`, `withdrawn`, `ghosted`, `note`, `outreach_sent`.

`ghosted` is written by a nightly Lambda as a `source='system'` event. It is
the state everyone actually lives in and no tracker models, and it is what
drives the follow-up queue in §7.

The UI is a vertical stepper on the application detail page: past events with
dates, the current state highlighted, and the two or three legal next
transitions as buttons. "Confirm you applied" is just `POST /applications`
from the posting card.

---

## 7 · Outreach

`GET /outreach/due` returns a daily queue, driven by rules, not vibes:

| Trigger | Action |
|---|---|
| `applied` + 10 days, no `acknowledged` | Draft a recruiter follow-up |
| `interviewed` + 1 day | Draft a thank-you |
| `interviewed` + 7 days, no next event | Draft a status check |
| `ghosted` | Draft one final polite close-out, then stop |

Drafts come from Bedrock with the student's profile, the posting, and the
event history as context — this is where GPA, school, and major earn their
place. Cap it at one draft per application per week so the tool can't generate
a pest.

**The app drafts. The student sends.** No automated sending in v1 — it's the
difference between a tool and a liability, and it also sidesteps a pile of
OAuth scope work.

---

## 8 · Integrations

| Provider | What you actually get | Verdict |
|---|---|---|
| **GitHub** | OAuth `read:user` + public repos, languages, pinned projects | Genuinely useful — infer skills from repo languages to seed `resume_skills`. Cheap, no review process. **Build it.** |
| **Gmail** | `gmail.readonly` or `gmail.metadata` to detect "thanks for applying" / interview invites and auto-advance the timeline | Works, with a caveat — see §9.3 |
| **LinkedIn** | Name, email, profile picture. **That's all.** | See §9.1 |

Tokens go in Secrets Manager (or SSM Parameter Store — free, and enough here),
referenced by ARN from `integrations.token_secret_arn`. Never in a column.

---

## 9 · Reality checks

These three are the parts of the original brief that don't survive contact
with the actual APIs. Better to know now.

### 9.1 LinkedIn cannot enrich a profile

Sign In with LinkedIn (OpenID Connect) is self-serve, but the only scopes
available are `openid`, `profile`, `email`, and `GET /v2/userinfo` returns
exactly: `sub`, `name`, `given_name`, `family_name`, `picture`, `locale`,
`email`, `email_verified`. **Positions, work history, education, and skills
are not available** at any self-serve tier — those sit behind partner programs
you will not get into as a student project.

So "LinkedIn integration" means: a sign-in button, and a `linkedin_url` field
on `contacts` that deep-links to a recruiter's profile from the outreach
screen. Both are worth having. Neither improves matching. Get profile
enrichment from the resume and from GitHub instead.

There is also a Cognito cost wrinkle: **OIDC and SAML federation is free only
to 50 MAU**, unlike the 10,000 MAU free allowance for the Essentials tier
generally. Google is a *social* provider — its users draw on the 10,000 MAU
pool like password users do. LinkedIn would have to be wired as a generic OIDC
provider, which puts it in the 50-MAU bucket. Given that it
buys you a name and an avatar, LinkedIn login is not worth its own MAU meter.
**Recommendation: Cognito email/password + Google social, LinkedIn as a
profile link only.**

### 9.2 Indeed has no API you can use

The Indeed Publisher API is deprecated and access is partner-only — employers,
ATS platforms, and agencies. There is no self-serve key.

The Indeed connector in this Claude session is a *research* tool: I can query
it (it just returned live Summer 2027 postings around College Park — Google
Reston at $82–109k, JHU APL Laurel, Peraton Herndon) and you can use it to
sanity-check coverage or hand-curate a seed list. **It is not something your
deployed app can call.** Treat Adzuna and USAJobs as the answer for breadth.

And don't scrape Indeed or company career pages to work around this. It
violates their terms, it breaks constantly, and it is the kind of thing that
turns a portfolio project into an awkward conversation in an interview.

### 9.3 Gmail's restricted scopes need a security assessment

`gmail.readonly`, `gmail.metadata`, and `gmail.modify` are all classified
**restricted**. An app that stores or transmits restricted-scope data on a
server must pass a CASA third-party security assessment before it can be
verified for public use — annually, at real cost and real effort.

What this means in practice:

- **In testing mode, you can add up to 100 test users with no verification.**
  They see an "unverified app" warning and click through it. For a portfolio
  project, a ColorStack pilot, or a demo, that is genuinely enough. Build it.
- **But test-mode refresh tokens expire after 7 days.** Every test user has to
  re-authorize weekly. (Authorizations limited to `openid`, `userinfo.email`,
  and `userinfo.profile` are exempt — but those are useless for reading mail.)
  Design the UI to expect a dead token and show a one-click reconnect, and
  don't let a stale Gmail link break the dashboard.
- Going public — anyone with a Google account signing in — means the
  assessment. Budget for it or don't promise it.
- **The escape hatch, if you ever need one:** give each student a unique
  forwarding address (`u-<hash>@inbox.step1.app`), receive with SES, drop to
  S3, parse in Lambda. Students forward or auto-forward confirmation emails.
  Zero Google review, and it works for Outlook and school mail too.

Plan on testing mode for v1 and design the email parser behind an interface so
the SES path is a swap, not a rewrite.

### 9.4 Two smaller ones

**Licensing.** The vanshb03 repo is MIT. **SimplifyJobs/Pitt CSC ships no
LICENSE file at all** — link out to the original posting URL, credit the list
in your README and in the UI, and don't present the dataset as yours. That's
both the right thing and the safe thing.

**Resumes are PII.** Private bucket, Block Public Access on, SSE-S3 (or KMS),
presigned PUT/GET with short expiry, no object ever served through the API,
and a real delete path when a student deletes their account.

---

## 10 · Cost

_Basis: us-east-1 on-demand, priced from AWS's published rates, September
2026. AWS changed the Free Tier to a credits model (~$100–200, 6 months) — if
your account is older than that you may still be on the legacy 12-month usage
tier. Check before you assume RDS is free, and note the AWS Free Tier itself
does not cover an Application Load Balancer's fixed hourly charge, only 750
hours of it in the first 12 months on eligible accounts — plan against the
full price below regardless._

This is revised upward from the ~$18–27/month estimate this document
originally gave, and it needs saying plainly: **the new number is higher, by
roughly double,** because that estimate priced App Runner, and App Runner is
no longer available to a service created after 30 April 2026 (§1). Its
replacement, ECS Express Mode, puts an Application Load Balancer in front of
the container the way a hand-rolled ECS setup always did — the thing App
Runner was originally chosen specifically to avoid paying for. There is no
version of "run one always-on FastAPI container behind HTTPS on AWS today"
that costs what App Runner used to.

| Item | Monthly | Source |
|---|---|---|
| Fargate, 0.25 vCPU / 0.5 GB, **ARM64** | $7.21 | [Fargate pricing][fargate-pricing] |
| Application Load Balancer (fixed hourly; LCU-hours on top, negligible at this traffic) | $16.43 | [ALB pricing][alb-pricing] |
| Public IPv4 addresses — one per ALB node (≥2, one per AZ) plus one for the Fargate task | $10.95 | [Public IPv4 pricing][ipv4-pricing] |
| RDS `db.t4g.micro` + 20 GB gp3, on-demand | $13.98 | [RDS pricing][rds-pricing] |
| Route 53 hosted zone (`step1careers.com`; alias queries to the ALB and Amplify are free) | $0.50 | [Route 53 pricing][route53-pricing] |
| S3 (resumes), ECR (one image), CloudWatch Logs, SSM Parameter Store | ~$2 | [S3][s3-pricing] · [ECR][ecr-pricing] · [CloudWatch][cw-pricing] |
| Cognito Essentials, <10,000 MAU | $0 | [Cognito pricing][cognito-pricing] |
| Amplify Hosting (build minutes + bandwidth at this traffic) | ~$1 | [Amplify pricing][amplify-pricing] |
| In-process ingest scheduler — runs inside the API task above | $0 | — no separate compute |
| **Fixed total** | **~$52–55** | |

[fargate-pricing]: https://aws.amazon.com/fargate/pricing/
[alb-pricing]: https://aws.amazon.com/elasticloadbalancing/pricing/
[ipv4-pricing]: https://aws.amazon.com/vpc/pricing/
[rds-pricing]: https://aws.amazon.com/rds/postgresql/pricing/
[route53-pricing]: https://aws.amazon.com/route53/pricing/
[s3-pricing]: https://aws.amazon.com/s3/pricing/
[ecr-pricing]: https://aws.amazon.com/ecr/pricing/
[cw-pricing]: https://aws.amazon.com/cloudwatch/pricing/
[cognito-pricing]: https://aws.amazon.com/cognito/pricing/
[amplify-pricing]: https://aws.amazon.com/amplify/pricing/

ARM64 is the recommended Fargate CPU architecture: it is roughly 20% cheaper
than x86 at the same size, ECS Express Mode has supported it since 18
September 2026, and it is what the development machine's own Docker builds
natively — one fewer thing that behaves differently in production than on a
laptop. `AWS_SETUP.md` §2.5 covers building for it.

Bedrock is the only variable line and is not in the fixed total above: scoring
is SQL, so the model is called once per feed page for the explanation blurbs
and once per outreach draft. Expect single-digit dollars per month at pilot
scale. Drop to a Haiku-class model and it's cents.

**Two things about this table are not verifiable without an AWS account**,
and are flagged rather than guessed at: whether the account's default VPC
subnets actually put the ALB in exactly 2 availability zones or more (the
public-IPv4 line assumes 2, priced from the AWS Price List API for
us-east-1 rather than read off the console, and `AWS_SETUP.md` §2.6 has you
pin the subnets explicitly for this reason); and Route 53's own domain
registration price, which changed structure on 1 July 2026 and is not
priced here at all — this project already has `step1careers.com`, registered
outside this work, and the table above covers only hosting it, not buying it.

For comparison, Rackner's fixed cost was ~$55–65/month, and this document's
own original App-Runner-based estimate was ~$18–27/month. The two cheapest
ways to bring the number down between demos, in order:

1. **Delete the Express Mode service** (removes the ALB and its IPv4
   charges — the largest two lines) **and stop the RDS instance.** Recreating
   the service from the same task definition and ECR image takes minutes;
   RDS auto-restarts itself after 7 days stopped, so if a pause runs longer
   than that, stop it again. This brings the running total to roughly the S3
   + Route 53 + Cognito lines — a few dollars a month.
2. Short of deleting it, Express Mode's own scale-to-one-task floor still
   carries the ALB and RDS instance-hours regardless of traffic, so a pause
   that keeps the service registered saves nothing worth doing over option 1.

---

## 11 · Repo layout

```
StEP1/
├── README.md
├── amplify.yml
├── docs/
│   ├── ARCHITECTURE.md        ← this file
│   ├── SCHEMA.md
│   └── COSTS.md
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── docker-compose.yml     ← local postgres
│   └── app/
│       ├── main.py  config.py  database.py  models.py  schemas.py
│       ├── auth.py  deps.py    logging_config.py
│       ├── routes/     health profile feed postings saved
│       │                applications outreach integrations
│       ├── services/   secrets storage matching resume_parse
│       │                outreach gmail github
│       ├── sources/    base simplify vanshb03 adzuna usajobs
│       └── llm/        gateway bedrock_client prompts mock
├── ingestion/
│   └── handler.py             ← Lambda entrypoint, imports backend.app.sources
├── frontend/
│   └── src/app  src/components  src/lib
└── .github/workflows/
    ├── backend-tests.yml
    └── ci.yml
```

`ingestion/` importing from `backend/app/sources/` keeps one normalizer, used
by both the Lambda and a local `python -m app.sources.backfill`.

---

## 12 · Build order

Each step ends with something demoable. That was the thing that worked about
the Rackner schedule.

| # | Deliverable | Depends on |
|---|---|---|
| 1 | Repo skeleton, Dockerfile, docker-compose Postgres, `GET /health`, CI green | — |
| 2 | Models + Alembic + `AUTH_MODE=local` register/login + `/me` | 1 |
| 3 | `sources/simplify.py` + `sources/vanshb03.py` + backfill script → 3,700 real postings in local Postgres | 2 |
| 4 | Profile CRUD, interests, S3 presign + resume text extraction | 2 |
| 5 | Scorer + `GET /feed` + `/feed/status` + saved postings | 3, 4 |
| 6 | Frontend: login, onboarding form, "starting your career…", dashboard, save | 5 |
| 7 | Applications + event timeline + stepper UI | 6 |
| 8 | Deploy: ECR + ECS Express Mode + RDS + Amplify + `AUTH_MODE=cognito` | 7 |
| 9 | Adzuna + USAJobs sources; EventBridge nightly ingest | 8 |
| 10 | GitHub OAuth → skill seeding | 8 |
| 11 | Outreach queue + Bedrock drafts | 7 |
| 12 | Gmail (testing mode) → auto events | 11 |

Steps 1–7 are a complete, honest product on a laptop. Step 8 is the only one
that costs money, and nothing before it is wasted if you stop there.

---

## 13 · Decisions I need from you

1. **App Runner or Lambda?** App Runner is ~$3/month and always warm. Lambda
   is ~$0 and cold-starts. Recommending App Runner; say the word if the $3
   matters more than the latency.
2. **RDS `db.t4g.micro` or Aurora Serverless v2 at min 0 ACU?** The t4g is
   flat ~$14/month ($0.016/hr + $0.115/GB-month gp3). Aurora can idle at zero
   compute — auto-pause after 5 minutes to 1 day, configurable — but bills
   $0.12/ACU-hour awake, keeps charging for storage while paused, and takes
   **~15 seconds to resume** (30s+ if it's been down over a day). A 15-second
   first page load is bad for a product whose pitch is a fast dashboard. For a
   demo-a-few-times-a-week project Aurora is cheaper; for a live pilot, t4g.
3. **Who is this for?** A portfolio project, or something you'd actually put
   in front of ColorStack UMD? That single answer changes the Gmail decision
   (testing mode vs assessment), the Cognito tier, and how much the licensing
   and PII sections in §9 matter.
4. **Scope beyond tech?** The GitHub lists are CS/quant/hardware only. If this
   should serve business, public health, and engineering majors too, Adzuna and
   USAJobs move from step 9 to step 3.

Answer 1–3 and the next deliverable is steps 1–3 of §12 scaffolded and pushed
to `AggreyN/StEP1`.
