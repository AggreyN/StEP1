# StEP1 — what you do by hand

Writing the application is automated; these are the things that isn't:
account-level setup, console clicks, and third-party keys. Each step says what
it **produces** — a value that ends up in `backend/.env` or an ECS task
definition environment variable.

Nothing here is needed to run the app locally. **Phase 0 and Phase 1 are all
you need for the first few weeks.** Phase 2 is deploy day.

---

## Phase 0 — before anything else (20 minutes)

### 0.1 Set a budget alarm. Do this first.

Billing → Budgets → Create budget → Cost budget → monthly, **$15**, alert at
80% and 100% to your email.

Do this before you create a single resource. The failure mode for a student
AWS account isn't a $2,000 surprise — it's a $30/month bill you don't notice
for five months. A budget alarm costs nothing and is the only thing standing
between you and that.

### 0.2 Know which Free Tier you're on

AWS moved new accounts to a **credits model** — roughly $100–200 in credits
over 6 months, after which the account closes unless you upgrade. Accounts
opened before that change may still be on the legacy 12-month usage tier.

Check Billing → Free tier. If you already have an account from the Rackner
project, assume some of it is spent. **Do not assume RDS is free.** The
~$14/month in §10 of the architecture doc is the number to plan against.

### 0.3 Stop using root

Create an IAM user (or IAM Identity Center user) for yourself with
`AdministratorAccess`, enable MFA on both it and root, then put the root
credentials away. Generate an access key for the IAM user and
`aws configure` it locally.

> **Produces:** working `aws sts get-caller-identity` on your laptop.

### 0.4 Pick one region and never change it

**`us-east-1`.** Every service below goes there. Cross-region anything is a
category of bug you don't need. It's also the region with the fewest
"not available here" surprises for Bedrock.

> **Produces:** `AWS_REGION=us-east-1`

---

## Phase 1 — needed during development

### 1.1 Adzuna API key — *needed at backend step 4*

Register at `developer.adzuna.com`. Instant, free, no review.

While you're there, read the terms on caching results — you're storing their
rows in your own database, and you should know what that permits.

> **Produces:** `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`

### 1.2 USAJobs API key — *needed at backend step 4*

Request at `developer.usajobs.gov/apirequest/`. Free; approval is usually
same-day.

Three headers are required on every call, and the middle one trips people up:

```
Host: data.usajobs.gov
User-Agent: ayertey.narh.24@gmail.com     ← the email you registered with
Authorization-Key: <your key>
```

> **Produces:** `USAJOBS_API_KEY`, `USAJOBS_USER_AGENT`

### 1.3 GitHub OAuth app — *needed at step 11, not before*

GitHub → Settings → Developer settings → OAuth Apps → New.
Callback `http://localhost:3000/api/auth/callback/github` for now; add the
Amplify URL later. Scope: `read:user` only.

> **Produces:** `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET`

### 1.4 Google Cloud project for Gmail — *needed at step 13, not before*

This is the fiddliest item, so leave it until last.

1. `console.cloud.google.com` → new project "StEP1".
2. APIs & Services → Enable **Gmail API**.
3. OAuth consent screen → **External**, publishing status **Testing**.
4. Add each friend's Google account under **Test users** — up to 100.
5. Credentials → OAuth client ID → Web application. Add both the localhost and
   Amplify callback URLs.
6. Scope: `gmail.readonly`.

Leave publishing status on **Testing** permanently. Going to "In production"
triggers the CASA security assessment for restricted scopes, and you will
never need it at this size.

Tell your friends two things: they'll see an "unverified app" warning and
should click through it, and **they'll have to reconnect weekly** — test-mode
refresh tokens expire after 7 days. That's not a bug in your app.

> **Produces:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`

---

## Phase 2 — deploy day (backend step 9)

Do these in order. Each depends on the one before.

### 2.1 S3 bucket for resumes

```bash
aws s3api create-bucket --bucket step1-resumes-<random> --region us-east-1
aws s3api put-public-access-block --bucket step1-resumes-<random> \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
aws s3api put-bucket-encryption --bucket step1-resumes-<random> \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

Bucket names are globally unique, so append something random.

Then add a **CORS rule** — without it the browser's presigned PUT fails with an
opaque network error and you will lose an hour to it:

```json
[{ "AllowedHeaders": ["*"],
   "AllowedMethods": ["PUT", "GET"],
   "AllowedOrigins": ["https://step1careers.com", "http://localhost:3000"],
   "ExposeHeaders": ["ETag"], "MaxAgeSeconds": 3000 }]
```

> **Produces:** `S3_BUCKET`, `STORAGE_BACKEND=s3`

### 2.2 RDS PostgreSQL

RDS → Create database → **Standard create** → PostgreSQL 16 → **Free tier**
template if offered, otherwise Dev/Test.

- Instance: **`db.t4g.micro`**
- Storage: 20 GB gp3, **turn off storage autoscaling** (it's how small
  databases quietly become expensive ones)
- Public access: **No**
- Encryption: **turn on storage encryption** (the default AWS-managed key is
  fine). This can only be chosen at creation — an unencrypted instance cannot
  be encrypted later without a snapshot restore — so do it before there is
  any data in it
- Backups: 7 days
- Note the master username and password — put them in Secrets Manager, not a
  text file

For local development against it, either use an SSH tunnel through a bastion,
or just keep developing against the local Docker Postgres. **The second option
is better** — you don't need cloud data on your laptop.

> **Produces:** `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/step1`

### 2.3 Cognito user pool

Cognito → Create user pool.

- Sign-in: **Email**
- **Self-service sign-up: OFF.** This is the invite-only decision from §13 of
  the architecture doc, and it's one checkbox. It removes the abuse surface,
  the email-verification flow, and any chance of a stranger's resume in your
  bucket.
- Feature plan: **Essentials** (10,000 free MAU — you'll use single digits)
- Google as a social identity provider, if you want one-click sign-in.
  Google users draw on the same free MAU pool.
  **Skip LinkedIn** — it would be a generic OIDC provider, and OIDC federation
  is free only to 50 MAU, for a name and an avatar.
- App client: choose the **single-page application (SPA)** type, which gives
  you a client with **no secret** and authorization-code + PKCE. The console's
  "Traditional web application" and "Machine-to-machine" types now generate a
  secret, which a browser app cannot hold safely — if you see a client secret
  on the summary screen, you picked the wrong type.
  Callback URLs: `http://localhost:3000/` and `https://step1careers.com/`.

Add your friends with:

```bash
aws cognito-idp admin-create-user --user-pool-id <id> \
  --username friend@example.com --user-attributes Name=email,Value=friend@example.com
```

> **Produces:** `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`, `AUTH_MODE=cognito`

### 2.4 Secrets Manager (or SSM Parameter Store)

Store `DATABASE_URL` and `JWT_SECRET` — the only two settings
`backend/.env.production.example` marks `[secret]`. `COGNITO_USER_POOL_ID`
and `COGNITO_APP_CLIENT_ID` go through the same `get_secret()` indirection
if you ever want them out of the task definition too, but they aren't
secrets in the sense that matters here; a plain environment variable is fine
for them.

`services/secrets.get_secret()` reads these when `APP_ENV=prod` (or whenever
`SECRETS_BACKEND=secretsmanager`) and falls back to a plain environment
variable otherwise — so this is a config change, not a code change. On ECS
the recommended path skips the API call entirely: put each value in SSM
Parameter Store and reference it from the task definition's `secrets` list
(`valueFrom` the parameter ARN). ECS's task execution role fetches it and
hands it to the container as an environment variable before your code ever
runs, so `SECRETS_BACKEND=env` (the default) is correct and the container
needs no Secrets Manager permission of its own.

**SSM Parameter Store standard parameters are free**; Secrets Manager is
$0.40/secret/month, which is $0.80/month for two. At this scale either is
fine — SSM only wins on cost once the price of remembering it exists.

> **Produces:** `APP_ENV=prod`, two SSM parameters (or Secrets Manager ARNs)
> for the task definition's `secrets` list.

### 2.5 ECR + push the image

```bash
aws ecr create-repository --repository-name step1-api
aws ecr get-login-password | docker login --username AWS --password-stdin <acct>.dkr.ecr.us-east-1.amazonaws.com

# ARM64 — see the note below for why.
docker build --platform linux/arm64 -t step1-api ./backend
docker tag step1-api:latest <acct>.dkr.ecr.us-east-1.amazonaws.com/step1-api:latest
docker push <acct>.dkr.ecr.us-east-1.amazonaws.com/step1-api:latest
```

**Build for `linux/arm64`, and set the task definition's CPU architecture to
`ARM64` to match (§2.6).** Three reasons, in order of how much they matter:
it is roughly 20% cheaper per vCPU-hour and per GB-hour than x86_64 on
Fargate; ECS Express Mode has supported ARM64 tasks since 18 September 2026,
so nothing is traded away to get the discount; and if you are building on an
Apple Silicon Mac, `docker build` produces an ARM64 image by default, so this
is also the one architecture choice that needs no `--platform` flag and no
emulation to build. Confirmed against this repository's own dependencies: a
plain `docker build --platform linux/arm64` pulls `manylinux ... aarch64`
wheels for every package that ships one (`psycopg[binary]`, `PyMuPDF`,
`cryptography`, `bcrypt`) with nothing compiled from source, and the built
image starts, passes its own `HEALTHCHECK`, and serves an authenticated
request. Cross-building for `linux/amd64` from the same Dockerfile also
resolves cleanly if you ever need an x86 fallback — neither architecture is a
trap — but there is no cost or compatibility reason left to prefer it.

### 2.6 ECS Express Mode

App Runner is **closed to new customers from 30 April 2026**
([AWS, *App Runner service availability change*][apprunner-eol]) — a service
created after that date cannot use it, full stop. AWS's own replacement path
for "one container, HTTPS, no infrastructure to hand-assemble" is
**ECS Express Mode**: one `create-express-gateway-service` call (or its
console equivalent) that creates a cluster, a task definition, a service with
canary deployment and alarm-based rollback, an Application Load Balancer
(HTTPS listener, target group, security groups), a service-linked role, an
autoscaling target and policy, a CloudWatch log group, and a metric alarm —
all as one unit
([AWS, *How Amazon ECS works with Express Mode services*][express-work]).
Tear it down and all of it goes with it, except the log group, which AWS's
own guidance says is retained on purpose
([AWS, *Best practices*][express-best-practices]) — expect a small,
permanent CloudWatch Logs storage charge unless you delete the log group
yourself afterward.

```bash
aws ecs create-express-gateway-service \
  --service-name step1-api \
  --image <acct>.dkr.ecr.us-east-1.amazonaws.com/step1-api:latest \
  --cpu 256 --memory 512 \
  --cpu-architecture ARM64 \
  --container-port 8000 \
  --health-check-path /health \
  --subnets subnet-aaa subnet-bbb \
  --environment-variables APP_ENV=prod ... \
  --secrets DATABASE_URL=arn:aws:ssm:... JWT_SECRET=arn:aws:ssm:...
```

Set every one of these explicitly rather than accepting whatever the CLI
defaults to; AWS's own reference pages disagree with each other about what
the unstated defaults even are (some say 256 CPU units / 512 MiB and a
`/ping` health path, the console-facing guide says 1024 / 2048 and `/`), so
there is no default worth trusting either way.

- **Port 8000, health check path `/health`.** `/health` answers fast,
  unauthenticated, and 503s the instant the database is unreachable — built
  for exactly this (backend's own hardening work; see `backend/README.md`).
- **CPU architecture: `ARM64`.** Cheaper, supported by Express Mode since 18
  September 2026, and what a Docker build on an Apple Silicon Mac produces
  without a `--platform` flag (§2.5).
- **0.25 vCPU / 0.5 GB** to start. This is a JSON API in front of Postgres,
  not a model server; scale the task size up only if `/stats` or the ingest
  scheduler's memory use says to.
- **Scale to exactly one task.** Set both min and max capacity to 1.
  `AUTO_INGEST`'s advisory lock (backend's own hardening work) is written to
  be safe if a second task ever did start, but there is nothing here two
  tasks would do faster — the rate limiter's per-process counters, the
  in-memory ingest lock, and the point of running a single small always-on
  service all assume one.
- **Environment and secrets**, from `backend/.env.production.example`:
  everything without `[secret]` goes under `--environment-variables`
  (`APP_ENV=prod`, `AUTH_MODE`, `TRUST_PROXY=true`,
  `TRUSTED_PROXY_HOPS=1`, `ALLOWED_ORIGINS=https://step1careers.com`,
  `PUBLIC_API_BASE=https://api.step1careers.com`, `AUTO_INGEST=true`, and the
  rest); `DATABASE_URL` and `JWT_SECRET` go under `--secrets`, pointing at
  the SSM parameters from §2.4.
- **Task execution role**: `ssm:GetParameters` (or
  `secretsmanager:GetSecretValue`) for the two secrets above — this is the
  standard `ecsTaskExecutionRole` /
  `AmazonECSTaskExecutionRolePolicy`
  ([AWS, *Task execution IAM role*][task-execution-role]), separate from
  whatever the *task role* needs at runtime (`s3:GetObject`/`PutObject` on
  your bucket, `bedrock:InvokeModel` later).

#### Networking — the old App Runner problem does not recur here, but read this anyway

The App Runner version of this document spent most of a page on a VPC
connector forcing all outbound traffic through a NAT gateway, breaking
Cognito's JWKS fetch, and costing $32/month to fix. **Express Mode does not
have that problem**, because its default topology is different: the task
runs in the same public subnets as the ALB, with a public IP of its own,
reaching the internet directly through the VPC's internet gateway — no VPC
connector, no forced NAT detour
([AWS, *How Express Mode works*][express-work]). That is also *why* the
cost table in `docs/ARCHITECTURE.md` §10 has a line for "public IPv4
addresses": the ALB's own nodes (at least one per availability zone) and the
task each hold one, and each is billed hourly.

What "no NAT" does **not** mean is "no security groups." Set these
explicitly rather than accepting whatever a wizard proposes:

| Security group | Inbound | Outbound |
|---|---|---|
| **ALB** (created by Express Mode) | 443 from `0.0.0.0/0` (and 80, redirected to 443) | to the task SG, container port |
| **Task** | from the **ALB's security group only**, container port 8000 | 5432 to the **RDS security group**; 443 to `0.0.0.0/0` (Cognito JWKS, S3, GitHub's raw content host) |
| **RDS** | 5432 from the **task's security group** — not a CIDR | — |

RDS's own **"Public access: No"** setting (§2.2) still matters even though
it sits in a VPC that has public subnets: that flag controls whether AWS
attaches a public IP to the instance at all, and the security group above is
what actually decides who can open a connection. Keep both.

The S3 gateway endpoint the App Runner section recommended was there to give
a NAT-routed task a way to reach S3 without paying for NAT data processing.
It is no longer load-bearing — the task already reaches S3 over the public
internet through the internet gateway — but it is still free and still
shaves a little latency and data-transfer cost off every resume upload check,
so add it if convenient: VPC → Endpoints → `com.amazonaws.us-east-1.s3`,
Gateway type, associated with the task's route table.

If the service comes up but every request 500s on a database timeout, it's
the RDS security group. If `/health` is fine but every authenticated request
fails, check the task's outbound rule for port 443 before suspecting Cognito
itself.

> **Produces:** the ALB's default `https://<service-name>.ecs.us-east-1.on.aws/`
> URL, good for testing before the domain in §2.7 is wired up.

### 2.7 HTTPS and the domain — step1careers.com

This project's domain is **step1careers.com**, registered separately from
this setup — nothing here registers it. What's left is pointing it at the
two things it needs to reach: the ALB from §2.6, and Amplify in §2.8.

1. **DNS.** If the domain's registrar is Route 53, skip to step 2. If it's
   an external registrar, either delegate the domain to a Route 53 hosted
   zone (create the zone, copy its four NS records into the registrar) or
   create the records below at the external registrar directly — Route 53
   is not required, only convenient if you're already touching AWS for
   everything else.
2. **A certificate.** ACM → Request a public certificate for
   `api.step1careers.com` (DNS validation; ACM is free). Express Mode adds
   it to the ALB's HTTPS listener for you when you attach a custom domain
   through the console's "Custom domains" panel, or you can add it to the
   listener's certificate list yourself.
3. **`api.step1careers.com` → the ALB.** A host-header rule on the HTTPS
   listener routing that hostname to the target group, plus a Route 53 alias
   record (or a CNAME, at an external registrar) pointing
   `api.step1careers.com` at the ALB's DNS name. Express Mode "will not
   overwrite changes unless requested"
   ([AWS, *Advanced customization*][express-advanced]), so this survives a
   later `update-express-gateway-service`.
4. **`step1careers.com` → Amplify.** Covered in §2.8; Amplify issues and
   renews its own certificate for a domain you attach to it, separately from
   the ACM certificate in step 2.
5. Once both resolve, set `ALLOWED_ORIGINS=https://step1careers.com` and
   `PUBLIC_API_BASE=https://api.step1careers.com` on the ECS service (§2.6),
   and `NEXT_PUBLIC_API_BASE=https://api.step1careers.com` on Amplify (§2.8).

> **Produces:** `https://api.step1careers.com` serving the API,
> `https://step1careers.com` serving the frontend.

### 2.8 Amplify Hosting — a static site, not SSR

The frontend is client-rendered and built as a **static export**
(`next build` with `output: "export"`, producing a plain `out/` directory of
HTML/CSS/JS) rather than run through Amplify's Next.js SSR compute. This
matters because AWS's own SSR support for Amplify Hosting is documented for
**Next.js 12 through 15** ([AWS, *SSR support*][amplify-ssr]), and this
project is on Next.js 16 — there is no SSR path here to fall into by
accident, but it also means the frontend cannot be deployed the "default"
Next.js way Amplify's own quickstart assumes.

Amplify → Host web app → GitHub → repo `AggreyN/StEP1` → branch `main`,
`appRoot: frontend`. Two build-output settings the frontend's own
`amplify.yml` must get right for a static export to serve correctly:

- `baseDirectory` in `amplify.yml` must point at `out`, not `.next` — `.next`
  is the build cache for Amplify's *SSR compute* platform, and pointing a
  static site at it serves nothing.
- Response headers (CSP, `Strict-Transport-Security`, and the rest of the
  hardened set this backend already sends) belong in Amplify's own
  `customHttp.yml` at the frontend's root, which is the currently documented
  place for them; `amplify.yml`'s `customHeaders` block is AWS's earlier
  mechanism for the same thing and still works, but the two should not both
  try to set the same header. **Check which one the frontend build actually
  uses before deploy day** — this document does not own `amplify.yml` and
  cannot promise which one it currently is.

Custom domain: Amplify → Domain management → add `step1careers.com`, verify
it (DNS, same as §2.7), and Amplify provisions and renews its own
certificate for it. Environment variables:
`NEXT_PUBLIC_API_BASE=https://api.step1careers.com`, `NEXT_PUBLIC_COGNITO_*`.

Then go back and add `https://step1careers.com` to three places if you
haven't already: the S3 CORS rule (§2.1), the Cognito app client callback
URLs (§2.3), and the API's `ALLOWED_ORIGINS` (§2.6). Forgetting the third is
the classic "works locally, CORS error in production."

### 2.9 Keeping the listings fresh in production

**Recommended: do nothing extra.** `AUTO_INGEST=true` (already in
`backend/.env.production.example`) makes the API refresh the listings itself
once a day, from inside the same task that already needs to be running —
checked at boot and every `INGEST_CHECK_MINUTES` after, guarded by a
Postgres advisory lock so it is safe even if a second task briefly overlaps
during a deploy. There is nothing to schedule, nothing extra to pay for, and
nothing else to keep patched. This is the setup this section originally
described as the App-Runner-era alternative; with one always-on ECS task
instead of a separate nightly job, it is now the simpler default rather than
the fallback.

**EventBridge + Lambda remains the right answer when ingestion needs to run
somewhere other than the API task** — for instance, if the API ever scales to
more than one task (§2.6 recommends against that here, but a future version
might not), or if a refresh needs to run even while the API itself is
deliberately stopped between demos (§10's pause option 1 in
`docs/ARCHITECTURE.md`, which does stop ingestion along with everything
else). If that need arises: Lambda from a container image (reuse the ECR
image, different entrypoint) or a zip, timeout 5 minutes, memory 1 GB — the
default 3-second timeout will not finish a 16,000-row parse. It needs the
public internet (GitHub's raw content host) and needs to reach RDS; give it
its own security group, add an inbound rule on the RDS security group for
it, and leave it outside any VPC configuration that would force its traffic
through a NAT gateway — the same reasoning as §2.6, and for the same reason,
it does not need one. EventBridge Scheduler rule: `cron(0 8 * * ? *)` — 4am
Eastern — calling `python -m app.sources.backfill` in the Lambda, with
`AUTO_INGEST=false` on the ECS service so the two don't race.

[apprunner-eol]: https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html
[express-work]: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-work.html
[express-best-practices]: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-best-practices.html
[express-advanced]: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-advanced-customization.html
[task-execution-role]: https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_execution_IAM_role.html
[amplify-ssr]: https://docs.aws.amazon.com/amplify/latest/userguide/ssr-amplify-support.html

### 2.10 Bedrock access — *only when you build step 12*

Foundation-model access is now **enabled by default** in commercial regions —
the old per-region "request model access" dance is gone. Two things still
apply:

- Your account needs AWS Marketplace permissions and a valid payment method.
- **Anthropic models require a one-time use-case form, once per account.**
  Fill it in Bedrock → Model access before your first invoke.

First invocation of a third-party model can take up to ~15 minutes while the
subscription completes. Don't debug a timeout that's actually just that.

Nothing before step 12 needs any of this.

---

## Order of operations, condensed

| When | Do |
|---|---|
| Today | Budget alarm, IAM user, region. Adzuna + USAJobs keys. |
| Backend step 4 | Nothing new — the keys from above. |
| Deploy day | S3 → RDS → Cognito → SSM → ECR → ECS Express Mode → domain/HTTPS → Amplify, in that order. |
| Step 11 | GitHub OAuth app. |
| Step 12 | Bedrock model access. |
| Step 13 | Google Cloud project, Testing mode, add friends as test users. |

## Teardown

Between demos, or once recruiting season ends: **delete the Express Mode
service** and **stop the RDS instance**.

Deleting the service (`aws ecs delete-express-gateway-service` or the console
equivalent) removes the ALB with it — Express Mode owns that ALB and tears it
down along with everything else it created in §2.6, which is also why the two
biggest lines in the cost table (the ALB itself and the public IPv4 addresses)
disappear with it. Stopping RDS (it auto-restarts after 7 days, so stop it
again if the pause runs longer, or take a final snapshot and delete the
instance outright) removes the third-biggest line. Together these take the
~$52–55/month in `docs/ARCHITECTURE.md` §10 to roughly the S3 + Route 53 +
Cognito lines — a few dollars a month, not zero, since the domain's hosted
zone and whatever is already in S3 keep costing their small flat amounts
regardless.

Two things this doesn't clean up, both cheap but worth knowing about:

- **The CloudWatch log group is retained on purpose** even after the service
  that wrote to it is deleted
  ([AWS, *Best practices*][express-best-practices]). Delete it by hand
  (`aws logs delete-log-group`) if you want the small per-GB storage charge
  gone too, or leave it — it's a few cents at this volume.
- **ECR keeps the image you pushed** until you delete the repository or the
  image itself; small ($0.10/GB-month) but not automatic.

Bringing the service back is `aws ecs create-express-gateway-service` again
from the same ECR image and task definition — the steps in §2.6, minus
anything you didn't change (SSM parameters, the ACM certificate, and DNS all
survive a deleted service). S3, RDS's snapshot (if you took one instead of
just stopping it), and the Cognito pool all cost nothing at rest either way.
None of this touches `step1careers.com`'s registration, which lives with the
registrar and isn't part of anything created in this document.
