# Claude Code brief — `frontend` branch

Paste this whole file as your first message in Claude Code, with
`docs/ARCHITECTURE.md` open in the repo.

---

You are working on **StEP1**, an internship discovery and application tracker.
The design is in `docs/ARCHITECTURE.md` — read §5 (API surface), §6
(application timeline), and §2.6 (role taxonomy) before writing code.

## Branch setup

```bash
git checkout main
git checkout -b frontend
```

All work in `frontend/`. Do not touch `backend/` — a parallel branch owns it.

## The core constraint: build against mocks

The backend does not exist yet. **Build the entire UI against local mock JSON**
in the exact shapes below, behind one API client module. When the backend
lands, flipping `NEXT_PUBLIC_API_BASE` from `mock` to a real URL is the only
change.

This is how the Rackner frontend was built (a locked `mock-obligations.json`
while the API was still weeks out) and it worked — do the same:

```
frontend/src/lib/
  api.ts        // every fetch goes through here. Reads NEXT_PUBLIC_API_BASE.
                // When it is "mock", resolve from src/lib/mock/*.json with a
                // 300ms delay so loading states are real, not theoretical.
  mock/         // feed.json, profile.json, applications.json, status.json
  types.ts      // TypeScript types matching the shapes below, hand-written
```

No component imports mock data directly. If one does, the swap breaks.

## Stack

Next.js (App Router) + TypeScript + Tailwind. Match the Rackner frontend's
setup. Playwright for tests. No component library — build the eight or so
components you need.

## Screens

### 1 · Login — `/login`

Email + password, register/login toggle. Store the token in memory plus
`localStorage`, attach as `Authorization: Bearer`. A `useRequireAuth()` hook
redirects unauthenticated users; every other route uses it.

Note in a comment that this will be replaced by Cognito's hosted UI — keep the
token-handling in `lib/auth.ts` so the swap is one file.

### 2 · Onboarding — `/onboarding`

One page, sectioned, not a multi-step wizard — it's six fields and a file
upload, and wizards make that feel longer than it is.

- School (default "University of Maryland, College Park"), major, minor
- Degree level, expected graduation year, GPA
- Target terms — multi-select from `Summer 2027`, `Fall 2027`, `Winter 2027`,
  `Spring 2027`, `Summer 2028`
- Preferred locations (free text chips) + a "remote is fine" toggle
- **Fields of interest: pick 3–5 and rank them.** This is the most important
  control on the page, so give it room. Drag-to-reorder, or up/down arrows —
  but the rank must be visible as `1, 2, 3…`, because rank drives the score.
  Options come from `ROLE_LABELS` — mirror the 14 real roles from §2.6 into
  `lib/roles.ts` (exclude `other`).
- Resume upload → `POST /profile/resume/presign`, then PUT the file straight
  to the returned URL, then `POST /profile/resume/commit`. Show extracted
  skills as chips once it returns, and let the user delete any that are wrong.

Validate 3–5 interests client-side and disable submit until satisfied.

### 3 · "Starting your career…" — `/onboarding/building`

`PUT /profile` returns **202**. Land here, poll `GET /feed/status` on the
interval in `Retry-After`, and render the real `step` string the API sends:
_Reading your resume → Scanning 4,139 open internships → Ranking your matches_.
Show the `pct` as a progress bar.

This will often finish in under two seconds. **That's fine — do not add an
artificial delay.** If `state` is already `ready` on the first poll, route
straight through. If it's still building after 30 seconds, show a "this is
taking longer than usual" message with a link to the dashboard anyway.

### 4 · Dashboard — `/`

The main screen. A scored, sorted list of posting cards.

Each card: title, company, location(s), term, **role chips**, posted-age, the
score as a badge, and the `reasons` rendered as small chips — that last part is
the product's whole differentiator, so don't bury it. Save (star) and "I
applied" actions live on the card.

Filters in a left rail or a top bar: role (multi-select), location, term,
minimum score, and a remote toggle. Filters are URL query params so a filtered
view is linkable and survives refresh.

Empty states matter here and will be hit for real — the niche role families
are thin (see §2.6: 30 solutions-engineering postings, 4 TPM). When a filter
returns nothing, say which filter is responsible and offer to relax it. Do not
render a blank page.

### 5 · Saved — `/saved`

Same cards, filtered to saved. Optimistic toggle with rollback on error.

### 6 · Applications — `/applications` and `/applications/[id]`

List view grouped by status with a count per group.

Detail view is the timeline. A **vertical stepper**: past events with dates and
notes, the current state highlighted, and buttons rendered from the API's
`next_transitions` array. **Do not hard-code the state graph in the
frontend** — the backend owns it and sends the legal moves. Each transition
opens a small dialog for an optional date and note, then
`POST /applications/{id}/events`.

Include the `ghosted` state in the visual design. It is written by a nightly
job, not by the user, and it should look different from a rejection — greyed
out and quiet, not red.

## Shared response shapes — the contract

The `backend` branch implements exactly these. Write your mock JSON to match,
field for field. **If you need a field that isn't here, ask — don't invent
one**, because a name you make up will not exist when the API arrives.

```jsonc
// GET /feed  → each item, and GET /postings/{id}
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

{ "items": [...], "page": 1, "total": 412, "has_more": true }          // GET /feed
{ "state": "building", "pct": 40, "step": "Scanning 4,139 open internships" }  // GET /feed/status

// GET /profile
{ "school": "University of Maryland, College Park", "major": "Information Science",
  "minor": "Data Science", "degree_level": "Bachelor's", "grad_year": 2028,
  "gpa": 3.7, "target_terms": ["Summer 2027"],
  "preferred_locations": ["Washington, DC"], "remote_ok": true,
  "interests": [ { "role": "software", "label": "Software Engineering", "rank": 1 } ],
  "resume": { "filename": "resume.pdf", "uploaded_at": "...", "skills": ["Python"] },
  "profile_version": 3 }

// GET /applications/{id}
{ "id": 12, "posting": { ... }, "status": "interview_scheduled",
  "applied_at": "2026-09-01T...",
  "events": [ { "id": 40, "kind": "applied", "occurred_at": "...", "note": null, "source": "manual" } ],
  "next_transitions": ["interviewed", "rejected", "withdrawn"] }

{ "detail": "human-readable message" }                                  // errors
```

Make the mock `feed.json` **at least 40 varied items** — different roles,
scores from 20 to 95, some remote, some with salary and some without, a couple
already saved, a couple with an `application`. A three-item mock hides every
layout bug you're about to ship.

## Design notes

Clean and quiet. This is a tool someone opens daily during recruiting season
while already stressed, so: high information density without clutter, generous
tap targets, and no animation that delays reading. One accent color, used for
score badges and primary actions only.

Dark mode via Tailwind's `dark:` and `prefers-color-scheme`. Define colors as
CSS variables in `globals.css` so the palette is one file.

Mobile matters — people check postings on their phone between classes. The
card list must be usable at 375px, filters collapsing into a sheet.

## Acceptance — how I'll check

1. `npm run dev` with `NEXT_PUBLIC_API_BASE=mock` → every screen navigable
   with no backend running.
2. Onboarding refuses to submit with 2 or 6 interests; accepts 3–5; rank is
   visible and reorderable.
3. The building screen polls, shows real step text, and routes through on
   `ready` — including when `ready` arrives on the first poll.
4. Dashboard filters write to the URL; reloading a filtered URL restores it.
5. Every filter combination that returns zero results shows a specific empty
   state naming the responsible filter.
6. Timeline buttons come from `next_transitions`; the state graph appears
   nowhere in the frontend source.
7. Playwright covers: login → onboarding → building → dashboard → save →
   apply → advance the timeline.
8. Usable at 375px with no horizontal scroll.
9. `grep -r "mock" src/components/` returns nothing.

## Working style

- Commit per screen.
- Build the API client and types first, then screens against them.
- If a screen needs data the contract doesn't carry, **stop and tell me** so I
  can add it to both briefs at once.
- Stop when acceptance passes. Do not wire real auth, Cognito, or Amplify.
