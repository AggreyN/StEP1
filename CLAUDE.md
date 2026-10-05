# StEP1 — working notes for Claude Code

Internship discovery and application tracking. Python/FastAPI on App Runner,
Postgres on RDS, Next.js on Amplify, Cognito for auth. Private and
invite-only.

Full design: `docs/ARCHITECTURE.md`. Security: `docs/HARDENING.md`.
Branch briefs: `docs/briefs/`.

---

## Design skills — scope rule

`design-taste-frontend` (taste-skill) is installed in this project. Its own
first line says:

> Landing pages, portfolios, and redesigns. **Not dashboards, not data tables,
> not multi-step product UI.**

Respect that. It is not advice, it is the skill's stated scope.

| Route | Use taste-skill? | Why |
|---|---|---|
| `/about`, `/`, `/privacy` (marketing + static) | **Yes** | Read once, judged on looks |
| `/onboarding`, `/onboarding/building` | **No** | Multi-step product UI |
| `/` dashboard, `/saved` | **No** | Dense scannable list, opened daily |
| `/applications`, `/applications/[id]` | **No** | Data + state machine UI |

For the product screens, follow `docs/briefs/FRONTEND_BRIEF.md` instead. Those
are scanned and operated, not read. High information density, fast first
paint, no decorative motion.

### Dials, when taste-skill does apply

Baseline is 8 / 6 / 4. Override it to:

```
DESIGN_VARIANCE: 6
MOTION_INTENSITY: 3
VISUAL_DENSITY: 3
```

Motion is deliberately below the skill's developer-portfolio preset of 5.
Scroll-triggered section reveals are a tell this project is specifically
avoiding. Hover states and focus transitions only.

Dials are set **conversationally**, never by editing SKILL.md.

### Other skills from that install

The bare `npx skills add` pulled in all 13 skills from the repo, including
`industrial-brutalist-ui`, `minimalist-ui`, and `high-end-visual-design`.
Their trigger descriptions overlap. Do not invoke them for this project — the
visual direction is already set below.

---

## Design tokens

Established by `frontend/src/app/about/page.tsx`. These are the site palette;
new pages use them rather than inventing colors.

```css
:root{
  --paper:#f6f7f6; --raise:#ffffff; --ink:#16191a; --ink-2:#4e5755;
  --ink-3:#7d8785; --line:#dfe4e2; --line-2:#c6cecb;
  --accent:#13603f; --accent-soft:#e6efea;
}
/* dark: --paper:#111413 --raise:#191d1c --ink:#e8ecea --ink-2:#a3aeaa
   --ink-3:#79837f --line:#252b29 --line-2:#374039
   --accent:#5cbc8c --accent-soft:#16291f  + color-scheme:dark */
```

Type: Source Serif 4 for prose, IBM Plex Sans for UI and labels, IBM Plex Mono
for numbers and the email address.

Borders are 4px radius. Not pills. Icons are SVG, never emoji.

---

## Copy rules

These exist because the project is explicitly trying not to read as
machine-generated.

- **No em dashes.** Use periods, commas, or colons. This applies to all
  user-facing copy, not to code comments.
- **No vague hero text.** "Supercharge your internship search" could describe
  forty products. Name the specific thing this one does.
- **Real numbers only, stated flat.** 4,139 active postings and 1,018
  companies are real figures from the ingest. Never animate them counting up,
  and never invent a metric, review, or testimonial.
- **No unsupported claims.** The scorer is a weighted sum. Do not call it
  AI-powered matching.

---

## Non-negotiables

Break these and the app is wrong, not just ugly.

1. **Every query touching a user's data filters by `user_id` from the JWT.**
   `GET /applications/{id}` returns 404, not 403, when the row belongs to
   someone else. See `docs/HARDENING.md` §7.
2. **`applications.status` is derived** from the newest row in
   `application_events`. Never settable by a caller.
3. **`app/sources/roles.py` is validated** against 4,139 real postings at
   0.17% unclassified. Do not rewrite it. Adding a role is a new tuple in
   `_RULES`, placed by specificity.
4. **`AUTH_MODE=local` must keep working** with no AWS account. It is why this
   project stays demoable on a laptop.
5. **`expose_headers=["Retry-After"]`** on the CORS middleware, or the
   `/feed/status` polling loop silently breaks.
6. **Secrets go through `services/secrets.get_secret()`.** Never a literal,
   never a committed `.env`.

---

## Conventions

Carried over from `github.com/AggreyN/Rackner-Project`, same author:
`app/routes/` one module per domain, SQLAlchemy 2.0 `Mapped[]`, Alembic for
every schema change, structured JSON access logs with a request id. Comments
explain why, not what.

---

_Keep this file short. It loads on every session, so anything that belongs in
`docs/` should live there and be linked, not copied._
