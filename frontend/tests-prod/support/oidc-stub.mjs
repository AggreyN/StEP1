// A stand-in for Amazon Cognito's managed login, for tests. No AWS.
//
//   node tests-prod/support/oidc-stub.mjs --port 3400 \
//     --client test-client \
//     --redirect http://localhost:3300/auth/callback \
//     --logout http://localhost:3300/login
//
// It has the endpoints the app uses, with Cognito's paths, parameters and
// error codes (Amazon Cognito developer guide: authorization endpoint, token
// endpoint, logout endpoint, PKCE):
//
//   GET  /oauth2/authorize   a page with buttons standing in for the person
//   POST /oauth2/token       authorization_code (PKCE checked) and refresh_token
//   GET  /logout             checks the sign-out URL, then redirects to it
//   GET  /.well-known/jwks.json
//
// and one of its own, for the specs:
//
//   GET  /__test/log?state=<state>   what it was asked during one sign-in,
//                                    and what it decided
//
// The sign-in page is a list of links, one per outcome. A spec can also add
// these to the address to shape that one sign-in (specs run side by side, so
// nothing here is a global switch):
//
//   __ttl=5          the ID token lasts 5 seconds
//   __refresh=fail   the refresh token is never accepted
//   __rotate=1       each refresh returns a new refresh token
//
// Tokens are RS256 JWTs signed with a key made at start-up.
import { createHash, createSign, generateKeyPairSync, randomUUID } from "node:crypto";
import http from "node:http";

const arg = (name, fallback) => {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? fallback : process.argv[i + 1];
};
const port = Number(arg("port", "3400"));
const CLIENT = arg("client", "test-client");
const REDIRECTS = arg("redirect", "").split(",").filter(Boolean);
const LOGOUTS = arg("logout", "").split(",").filter(Boolean);
const ISSUER = `http://localhost:${port}`;

const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const KID = "stub-key-1";
const jwk = { ...publicKey.export({ format: "jwk" }), kid: KID, alg: "RS256", use: "sig" };

const PEOPLE = {
  invited: { sub: "11111111-aaaa-bbbb-cccc-000000000001", email: "invited@umd.edu", name: "Invited Student" },
  second: { sub: "11111111-aaaa-bbbb-cccc-000000000002", email: "second@umd.edu", name: "Second Student" },
};

const CODE_SECONDS = 300; // "The authorization code is valid for five minutes."
const codes = new Map(); // code -> { challenge, redirect, nonce, person, issuedAt, used, state, options }
const refreshTokens = new Map(); // token -> { person, state, options }
const log = [];
const note = (entry) => log.push({ at: Date.now(), ...entry });

const b64 = (buf) => Buffer.from(buf).toString("base64url");

function jwt(claims) {
  const head = b64(JSON.stringify({ alg: "RS256", kid: KID, typ: "JWT" }));
  const body = b64(JSON.stringify(claims));
  const sig = createSign("RSA-SHA256").update(`${head}.${body}`).sign(privateKey);
  return `${head}.${body}.${b64(sig)}`;
}

function tokensFor(personKey, nonce, options) {
  const p = PEOPLE[personKey];
  const now = Math.floor(Date.now() / 1000);
  const common = { sub: p.sub, iss: ISSUER, iat: now, auth_time: now, exp: now + options.ttl, jti: randomUUID() };
  return {
    id_token: jwt({
      ...common,
      aud: CLIENT,
      token_use: "id",
      email: p.email,
      email_verified: true,
      name: p.name,
      "cognito:username": p.sub,
      ...(nonce ? { nonce } : {}),
    }),
    access_token: jwt({ ...common, client_id: CLIENT, token_use: "access", scope: "openid email profile", username: p.sub }),
    token_type: "Bearer",
    expires_in: options.ttl,
  };
}

const cors = { "Access-Control-Allow-Origin": "*" }; // as Cognito's token endpoint does
const json = (res, status, body, extra = {}) => {
  res.writeHead(status, { "Content-Type": "application/json;charset=UTF-8", ...cors, ...extra });
  res.end(JSON.stringify(body));
};
const redirect = (res, location) => {
  res.writeHead(302, { Location: location });
  res.end();
};
const page = (res, status, title, inner) => {
  res.writeHead(status, { "Content-Type": "text/html; charset=utf-8" });
  res.end(
    `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${title}</title></head>` +
      `<body><main><h1>${title}</h1>${inner}</main></body></html>`
  );
};

function body(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on("data", (c) => chunks.push(c));
    req.on("end", () => resolve(Buffer.concat(chunks).toString()));
  });
}

http
  .createServer(async (req, res) => {
    const url = new URL(req.url, ISSUER);
    const q = url.searchParams;

    if (req.method === "OPTIONS") {
      res.writeHead(204, { ...cors, "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Allow-Methods": "POST" });
      return res.end();
    }

    // ---------------- authorize ----------------
    if (req.method === "GET" && url.pathname === "/oauth2/authorize") {
      const request = Object.fromEntries(q);
      const state = q.get("state");
      if (q.get("__as")) note({ endpoint: "authorize", state, request });
      // Like Cognito: a bad client or redirect is shown here, never redirected.
      if (q.get("client_id") !== CLIENT) return page(res, 400, "Something went wrong", "<p>invalid client</p>");
      if (!REDIRECTS.includes(q.get("redirect_uri") ?? "")) {
        return page(res, 400, "Something went wrong", "<p>redirect_mismatch</p>");
      }
      const back = (params) => {
        const u = new URL(q.get("redirect_uri"));
        for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
        if (q.get("state")) u.searchParams.set("state", q.get("state"));
        return u.toString();
      };
      if (q.get("response_type") !== "code") return redirect(res, back({ error: "invalid_request" }));
      if (!q.get("code_challenge") || q.get("code_challenge_method") !== "S256") {
        return redirect(res, back({ error: "invalid_request", error_description: "PKCE is required" }));
      }

      const decision = q.get("__as");
      if (!decision) {
        const link = (as, label) => {
          const u = new URL(url);
          u.searchParams.set("__as", as);
          return `<p><a data-testid="stub-${as}" href="${u.pathname}${u.search.replace(/&/g, "&amp;")}">${label}</a></p>`;
        };
        return page(
          res,
          200,
          "Stand-in sign-in page",
          "<p>This stands in for Amazon Cognito's managed login in tests.</p>" +
            link("invited", "Sign in as invited@umd.edu") +
            link("second", "Sign in as second@umd.edu") +
            link("cancel", "Cancel") +
            link("uninvited", "Sign in as someone who was not invited") +
            link("forged-state", "Come back with a state that is not ours") +
            link("slow", "Sign in, but too slowly (the code will have expired)")
        );
      }

      if (decision === "cancel") return redirect(res, back({ error: "access_denied", error_description: "User cancelled" }));
      if (decision === "uninvited") {
        return redirect(res, back({ error: "access_denied", error_description: "SignUp is not permitted for this user pool" }));
      }
      const code = randomUUID();
      codes.set(code, {
        challenge: q.get("code_challenge"),
        redirect: q.get("redirect_uri"),
        nonce: q.get("nonce"),
        person: decision === "second" ? "second" : "invited",
        issuedAt: decision === "slow" ? Date.now() - (CODE_SECONDS + 1) * 1000 : Date.now(),
        used: false,
        state,
        options: {
          ttl: Number(q.get("__ttl")) || 3600,
          refreshWorks: q.get("__refresh") !== "fail",
          rotate: q.get("__rotate") === "1",
        },
      });
      const u = new URL(back({ code }));
      if (decision === "forged-state") u.searchParams.set("state", "not-the-state-we-sent");
      return redirect(res, u.toString());
    }

    // ---------------- token ----------------
    if (req.method === "POST" && url.pathname === "/oauth2/token") {
      const form = new URLSearchParams(await body(req));
      const request = Object.fromEntries(form);
      const known = codes.get(form.get("code") ?? "") ?? refreshTokens.get(form.get("refresh_token") ?? "");
      const state = known?.state ?? null;
      const asked = { ...request, code_verifier: request.code_verifier ? "(given)" : undefined };
      const refuse = (error, why, description) => {
        note({ endpoint: "token", state, request: asked, refused: error, why });
        return json(res, 400, { error, ...(description ? { error_description: description } : {}) });
      };
      if ((req.headers["content-type"] ?? "").split(";")[0] !== "application/x-www-form-urlencoded") {
        return refuse("invalid_request", "content type");
      }
      if (req.headers.authorization || form.get("client_secret")) return refuse("invalid_client", "a public client has no secret");
      if (form.get("client_id") !== CLIENT) return refuse("invalid_client", "unknown client");

      if (form.get("grant_type") === "authorization_code") {
        const c = codes.get(form.get("code") ?? "");
        if (!c) return refuse("invalid_grant", "unknown code");
        if (c.used) return refuse("invalid_grant", "code already used");
        if (Date.now() - c.issuedAt > CODE_SECONDS * 1000) return refuse("invalid_grant", "code expired");
        if (form.get("redirect_uri") !== c.redirect) return refuse("unauthorized_client", "redirect mismatch", "invalid_redirect");
        const verifier = form.get("code_verifier") ?? "";
        if (!/^[A-Za-z0-9\-._~]{43,128}$/.test(verifier)) return refuse("invalid_grant", "verifier missing or malformed");
        const challenge = createHash("sha256").update(verifier).digest("base64url");
        if (challenge !== c.challenge) return refuse("invalid_grant", "verifier does not match the challenge");
        c.used = true;
        const refresh_token = `refresh-${randomUUID()}`;
        refreshTokens.set(refresh_token, { person: c.person, state, options: c.options });
        note({
          endpoint: "token",
          state,
          request: asked,
          grant: "authorization_code",
          pkce: "verified",
          person: c.person,
          verifierLength: verifier.length,
        });
        return json(res, 200, { ...tokensFor(c.person, c.nonce, c.options), refresh_token });
      }

      if (form.get("grant_type") === "refresh_token") {
        const token = form.get("refresh_token") ?? "";
        const held = refreshTokens.get(token);
        if (!held || !held.options.refreshWorks) return refuse("invalid_grant", "refresh token not accepted");
        note({ endpoint: "token", state, request: asked, grant: "refresh_token", person: held.person });
        // After the first sign-in, tokens last the usual hour: a spec that
        // asked for a short first token wants to see one refresh, not a storm.
        const out = tokensFor(held.person, null, { ...held.options, ttl: 3600 });
        if (held.options.rotate) {
          refreshTokens.delete(token);
          out.refresh_token = `refresh-${randomUUID()}`;
          refreshTokens.set(out.refresh_token, held);
        }
        return json(res, 200, out);
      }
      return refuse("unsupported_grant_type", "grant type");
    }

    // ---------------- logout ----------------
    if (req.method === "GET" && url.pathname === "/logout") {
      note({ endpoint: "logout", state: null, request: Object.fromEntries(q) });
      if (q.get("client_id") !== CLIENT || !LOGOUTS.includes(q.get("logout_uri") ?? "")) {
        return page(res, 400, "Something went wrong", "<p>The sign-out address is not one this client may use.</p>");
      }
      return redirect(res, q.get("logout_uri"));
    }

    if (req.method === "GET" && url.pathname === "/.well-known/jwks.json") return json(res, 200, { keys: [jwk] });

    // ---------------- for the specs ----------------
    if (url.pathname === "/__test/log") {
      const only = q.get("state");
      return json(res, 200, only ? log.filter((e) => e.state === only) : log);
    }
    if (url.pathname === "/__test/health") return json(res, 200, { ok: true });

    res.writeHead(404, { "Content-Type": "text/plain" }).end("Not found");
  })
  .listen(port, () => console.log(`oidc-stub: ${ISSUER} (client ${CLIENT})`));
