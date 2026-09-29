# StEP1 — what you do by hand

Claude Code writes the application. These are the things it can't do for you:
account-level setup, console clicks, and third-party keys. Each step says what
it **produces** — a value that ends up in `backend/.env` or an App Runner
environment variable.

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
   "AllowedOrigins": ["https://<your-amplify-domain>", "http://localhost:3000"],
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
  Callback URLs: `http://localhost:3000/` and your Amplify URL.

Add your friends with:

```bash
aws cognito-idp admin-create-user --user-pool-id <id> \
  --username friend@example.com --user-attributes Name=email,Value=friend@example.com
```

> **Produces:** `COGNITO_USER_POOL_ID`, `COGNITO_APP_CLIENT_ID`, `AUTH_MODE=cognito`

### 2.4 Secrets Manager (or SSM Parameter Store)

Store `DATABASE_URL`, `JWT_SECRET`, `ADZUNA_APP_KEY`, `USAJOBS_API_KEY`,
`GOOGLE_CLIENT_SECRET`, `GITHUB_CLIENT_SECRET`.

`services/secrets.get_secret()` reads these when `APP_ENV=prod` and falls back
to environment variables otherwise — so this is a config change, not a code
change.

**SSM Parameter Store standard parameters are free**; Secrets Manager is
$0.40/secret/month, which is ~$2.40/month for six. At this scale use SSM.

> **Produces:** `APP_ENV=prod`

### 2.5 ECR + push the image

```bash
aws ecr create-repository --repository-name step1-api
aws ecr get-login-password | docker login --username AWS --password-stdin <acct>.dkr.ecr.us-east-1.amazonaws.com
docker build -t step1-api ./backend
docker tag step1-api:latest <acct>.dkr.ecr.us-east-1.amazonaws.com/step1-api:latest
docker push <acct>.dkr.ecr.us-east-1.amazonaws.com/step1-api:latest
```

Build on the same CPU architecture you'll run on, or pass
`--platform linux/amd64`. An Apple Silicon image will not start on App Runner.

### 2.6 App Runner

App Runner → Create service → source **ECR** → your image → deploy trigger
**Automatic**.

- Port **8000**, health check path `/health`
- **0.25 vCPU / 0.5 GB** — the smallest config, ~$2.52/month idle
- Environment variables: everything the container needs
- Instance role: permissions for `s3:GetObject`/`PutObject` on your bucket,
  `ssm:GetParameter`, and `bedrock:InvokeModel` later

#### Networking — read this before you click anything

This is the one decision on deploy day that can quietly triple your bill, so
it gets its own section.

Your RDS instance is not publicly accessible, so App Runner cannot reach it on
default networking. The fix is a **VPC connector**: Networking → Outgoing
traffic → **Custom VPC**, create a connector in the RDS VPC and its private
subnets, then **edit the RDS security group** to allow inbound TCP 5432 from
the connector's security group.

**But a VPC connector routes *all* outbound traffic through the VPC.** Your
API loses the public internet — including the Cognito JWKS endpoint it needs
to validate every single token. The service comes up, health checks pass, and
every authenticated request fails. The usual remedy is a NAT gateway, which is
**~$32/month** — more than the rest of your stack combined.

Three ways out. Pick one deliberately:

| Option | Cost | Trade |
|---|---|---|
| **A. VPC connector + cached JWKS** | **~$0** | Private DB, no NAT. Fetch the pool's JWKS once, store it as an SSM parameter (or bake it into the image), and have `auth.py` read it from there instead of over HTTPS. It's a static public document and pools rotate keys rarely — but you must remember to refresh it if you ever do rotate. Add a free **S3 gateway endpoint** for resume access. |
| **B. VPC connector + interface endpoints** | ~$7/mo each | Cleanest. Interface endpoint for `cognito-idp` (and `bedrock-runtime` later), S3 gateway endpoint free. No NAT, no cached-key caveat. |
| **C. Public RDS, default egress** | $0 | Simplest, and what a lot of student projects do. Requires `sslmode=require`, a 40-character generated password, and a security group you keep narrow. It is still a database holding your friends' resumes, exposed to the internet. |

**Recommended: A, moving to B if key rotation ever bites.** Avoid C — the data
is other people's resumes, and "it's only my friends" is exactly the reasoning
that makes a breach embarrassing rather than merely unlucky.

Whichever you choose, if the service comes up but every request 500s on a
database timeout, it's the security group. If auth specifically fails while
`/health` is fine, it's the JWKS fetch.

> **Produces:** the API URL. Put it in `ALLOWED_ORIGINS` planning and in the
> frontend's `NEXT_PUBLIC_API_BASE`.

### 2.7 Amplify Hosting

Amplify → Host web app → GitHub → repo `AggreyN/StEP1` → branch `main`.

`amplify.yml` is already in the repo from the Rackner pattern; set
`appRoot: frontend`.

Environment variables: `NEXT_PUBLIC_API_BASE=<App Runner URL>`,
`NEXT_PUBLIC_COGNITO_*`.

Then go back and add the Amplify domain to three places: the S3 CORS rule, the
Cognito app client callback URLs, and the API's `ALLOWED_ORIGINS`. Forgetting
the third is the classic "works locally, CORS error in production."

### 2.8 EventBridge + ingest Lambda

Lambda from a container image (reuse the ECR image, different entrypoint) or a
zip. Same VPC config as App Runner so it can reach RDS. EventBridge Scheduler
rule: `cron(0 8 * * ? *)` — 4am Eastern.

Set the timeout to **5 minutes** and memory to 1 GB. The default is **3
seconds**, which will not finish a 16,000-row parse.

This Lambda *does* need the public internet (GitHub raw, Adzuna, USAJobs). If
you put it in the VPC for RDS access, that's the same egress problem as §2.6 —
simplest fix here is to give the ingest Lambda its own subnet with a NAT... or
don't. Instead: leave it **outside** the VPC and let it reach RDS over a
public endpoint restricted to the Lambda's security group, or run ingest as a
scheduled App Runner job path (`POST /admin/ingest` behind a shared secret,
called by EventBridge). The second option reuses networking you already have
and is the cheaper answer.

### 2.9 Bedrock access — *only when you build step 12*

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
| Deploy day | S3 → RDS → Cognito → SSM → ECR → App Runner → Amplify, in that order. |
| Step 11 | GitHub OAuth app. |
| Step 12 | Bedrock model access. |
| Step 13 | Google Cloud project, Testing mode, add friends as test users. |

## Teardown

When recruiting season ends: **pause the App Runner service** and **stop the
RDS instance** (it auto-restarts after 7 days, so stop it again or take a final
snapshot and delete it). That takes the ~$18–27/month to nearly zero. S3 and
the Cognito pool cost nothing at rest.
