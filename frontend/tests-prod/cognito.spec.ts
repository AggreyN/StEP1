// Sign-in through Cognito, on the exported site, against the stand-in
// sign-in service (support/oidc-stub.mjs). No AWS.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";
import { metaPolicy } from "../security-headers.mjs";
import { OIDC, SITES } from "./support/sites.mjs";

const SITE = SITES.cognito;
const STUB = `http://localhost:${OIDC.port}`;
test.use({ baseURL: `http://localhost:${SITE.port}` });

type Entry = {
  endpoint: string;
  state: string | null;
  request: Record<string, string>;
  grant?: string;
  pkce?: string;
  refused?: string;
  why?: string;
  verifierLength?: number;
};

const logFor = async (request: APIRequestContext, state: string): Promise<Entry[]> =>
  (await request.get(`${STUB}/__test/log?state=${encodeURIComponent(state)}`)).json();

/** Press "Sign in" and arrive at the sign-in service. Returns the request it was sent. */
async function leaveForSignIn(page: Page, from = "/login"): Promise<URLSearchParams> {
  if (!page.url().includes(from)) await page.goto(from);
  await page.getByTestId("cognito-sign-in").click();
  await page.waitForURL(`${STUB}/oauth2/authorize**`);
  await expect(page.getByRole("heading", { name: "Stand-in sign-in page" })).toBeVisible();
  return new URL(page.url()).searchParams;
}

/** What the person does on the sign-in service's page. */
async function choose(page: Page, as: string, options: Record<string, string> = {}) {
  const u = new URL(page.url());
  u.searchParams.set("__as", as);
  for (const [k, v] of Object.entries(options)) u.searchParams.set(k, v);
  await page.goto(u.toString());
}

async function signIn(page: Page, options: Record<string, string> = {}, as = "invited") {
  const asked = await leaveForSignIn(page);
  await choose(page, as, options);
  return asked.get("state")!;
}

async function onboard(page: Page) {
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByLabel("Major").fill("Information Science");
  for (const n of ["+ Security", "+ Software Engineering", "+ Research"]) {
    await page.getByRole("button", { name: n }).click();
  }
  await page.getByTestId("submit-profile").click();
  await expect(page).toHaveURL(/\/$/, { timeout: 20_000 });
  await expect(page.getByTestId("posting-card").first()).toBeVisible();
}

const stored = (page: Page) =>
  page.evaluate(() => ({
    token: localStorage.getItem("step1.token"),
    refresh: localStorage.getItem("step1.refresh"),
    expires: Number(localStorage.getItem("step1.expires")),
    user: JSON.parse(localStorage.getItem("step1.user") ?? "null"),
  }));

const claims = (token: string) => JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString());

/** Swap the stored token for one that has run out, without touching its
 *  recorded expiry: the app finds out from the API's 401, as it would if the
 *  clocks disagreed. */
async function expireToken(page: Page) {
  await page.evaluate(() => {
    const token = localStorage.getItem("step1.token")!;
    const [head, body] = token.split(".");
    const pad = (s: string) => s.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(s.length / 4) * 4, "=");
    const c = JSON.parse(atob(pad(body)));
    c.exp = Math.floor(Date.now() / 1000) - 60;
    const enc = btoa(JSON.stringify(c)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    localStorage.setItem("step1.token", `${head}.${enc}.expired`);
  });
}

const problem = (page: Page) => page.getByTestId("signin-problem");

async function expectAccessible(page: Page, screen: string) {
  await page.evaluate(() => document.fonts.ready);
  const { violations } = await new AxeBuilder({ page }).analyze();
  expect(
    violations.map((v) => ({ rule: v.id, help: v.help, nodes: v.nodes.slice(0, 3).map((n) => n.target.join(" ")) })),
    `${screen}: accessibility violations`
  ).toEqual([]);
}

// Every test here also fails on a Content-Security-Policy violation or a page error.
let trouble: string[] = [];
test.beforeEach(async ({ page }) => {
  trouble = [];
  page.on("console", (m) => {
    if (/Content Security Policy|Content-Security-Policy/i.test(m.text())) trouble.push(m.text());
  });
  page.on("pageerror", (e) => trouble.push(`page error: ${e.message}`));
});
test.afterEach(async ({ page }, info) => {
  if (info.status !== info.expectedStatus) {
    // what the person would have been looking at
    const text = await page.locator("body").innerText().catch(() => "(no page)");
    console.log(`\n[${info.title}] ended at ${page.url()}\n${text.slice(0, 600)}\n`);
  }
  expect(trouble).toEqual([]);
});

test("the sign-in page has no password form and no way to register", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByTestId("cognito-sign-in")).toBeVisible();
  await expect(page.locator("input")).toHaveCount(0);
  await expect(page.locator("form")).toHaveCount(0);
  await expect(page.getByRole("tab")).toHaveCount(0);
  await expect(page.getByText("Register")).toHaveCount(0);
  await expect(page.getByText("Create account")).toHaveCount(0);
  await expect(page.getByTestId("invite-only")).toContainText("Accounts are by invitation.");
  await expect(page.getByRole("main")).toContainText("StEP1 never sees your password.");
  expect(await page.locator("body").innerText()).not.toContain("—");
});

test("the page's policy lets the browser call the sign-in service, and only in this mode", async ({ page }) => {
  const expected = metaPolicy({ NODE_ENV: "production", ...SITE.env });
  expect(expected).toContain(`connect-src 'self' ${STUB};`);
  await page.goto("/login");
  expect(await page.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute("content")).toBe(expected);
  // the same build settings without cognito mode leave it out
  expect(metaPolicy({ NODE_ENV: "production", ...SITE.env, NEXT_PUBLIC_AUTH_MODE: "local" })).toContain(
    "connect-src 'self';"
  );
});

test("signing in: code and PKCE out, tokens back, and on to the app", async ({ page, request }) => {
  const asked = await leaveForSignIn(page);

  // what was sent to the authorization endpoint
  expect(asked.get("response_type")).toBe("code");
  expect(asked.get("client_id")).toBe(OIDC.client);
  expect(asked.get("redirect_uri")).toBe(SITE.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI);
  expect(asked.get("scope")).toBe("openid email profile");
  expect(asked.get("code_challenge_method")).toBe("S256");
  expect(asked.get("code_challenge")).toMatch(/^[A-Za-z0-9_-]{43}$/); // SHA-256, base64url
  expect(asked.get("state")).toMatch(/^[A-Za-z0-9_-]{20,}$/);
  expect(asked.get("nonce")).toMatch(/^[A-Za-z0-9_-]{20,}$/);
  expect(asked.get("nonce")).not.toBe(asked.get("state"));
  expect(asked.has("client_secret")).toBe(false);
  const state = asked.get("state")!;

  await choose(page, "invited");
  await expect(page).toHaveURL(/\/onboarding$/); // a new account goes to onboarding

  // what was sent to the token endpoint, and that the verifier was checked
  const log = await logFor(request, state);
  const exchange = log.filter((e) => e.endpoint === "token");
  expect(exchange).toHaveLength(1);
  expect(exchange[0].grant).toBe("authorization_code");
  expect(exchange[0].pkce).toBe("verified");
  expect(exchange[0].verifierLength).toBeGreaterThanOrEqual(43);
  expect(exchange[0].verifierLength).toBeLessThanOrEqual(128);
  expect(exchange[0].request.client_id).toBe(OIDC.client);
  expect(exchange[0].request.redirect_uri).toBe(SITE.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI);
  expect(exchange[0].request.client_secret).toBeUndefined();

  // what is kept: the ID token (sent to the API), a refresh token, no access token
  const s = await stored(page);
  const c = claims(s.token!);
  expect(c.token_use).toBe("id");
  expect(c.aud).toBe(OIDC.client);
  expect(c.email).toBe("invited@umd.edu");
  expect(c.nonce).toBe(asked.get("nonce"));
  expect(s.refresh).toMatch(/^refresh-/);
  expect(s.expires).toBe(c.exp * 1000);
  expect(s.user).toEqual({ id: c.sub, email: "invited@umd.edu", display_name: "Invited Student" });
  const everything = await page.evaluate(() => JSON.stringify({ ...localStorage, ...sessionStorage }));
  expect(everything).not.toContain('"token_use":"access"');
  expect(await page.evaluate(() => sessionStorage.getItem("step1.signin"))).toBeNull(); // the verifier is gone

  // and the API accepts it
  await onboard(page);
  await page.reload();
  await expect(page.getByTestId("posting-card").first()).toBeVisible();
});

test("the stand-in really checks the verifier: a different one is refused", async ({ page, request }) => {
  const asked = await leaveForSignIn(page);
  const state = asked.get("state")!;
  const authorize = page.url();

  // back on our site, swap the stored verifier for another well-formed one
  await page.goto("/about");
  await page.evaluate(() => {
    const pending = JSON.parse(sessionStorage.getItem("step1.signin")!);
    pending.verifier = "A".repeat(64);
    sessionStorage.setItem("step1.signin", JSON.stringify(pending));
  });
  await page.goto(authorize);
  await choose(page, "invited");

  await expect(problem(page)).toHaveAttribute("data-problem", "expired");
  const refused = (await logFor(request, state)).filter((e) => e.endpoint === "token");
  expect(refused).toHaveLength(1);
  expect(refused[0].refused).toBe("invalid_grant");
  expect(refused[0].why).toBe("verifier does not match the challenge");
  expect((await stored(page)).token).toBeNull();
});

test("a reply with someone else's state is refused before anything is exchanged", async ({ page, request }) => {
  const asked = await leaveForSignIn(page);
  await choose(page, "forged-state");
  await expect(page).toHaveURL(/\/auth\/callback\?/);
  await expect(page.getByRole("heading", { name: "Sign-in was stopped" })).toBeVisible();
  await expect(problem(page)).toHaveText(
    "This sign-in was not started from this browser tab, so it was stopped to keep your account safe. Start again from here."
  );
  expect((await logFor(request, asked.get("state")!)).filter((e) => e.endpoint === "token")).toEqual([]);
  expect((await logFor(request, "not-the-state-we-sent")).filter((e) => e.endpoint === "token")).toEqual([]);
  expect((await stored(page)).token).toBeNull();

  // starting again from the message works
  await page.getByTestId("signin-again").click();
  await page.waitForURL(`${STUB}/oauth2/authorize**`);
  await choose(page, "invited");
  await expect(page).toHaveURL(/\/onboarding$/);
});

test("a callback link opened where no sign-in was started is refused", async ({ page }) => {
  await page.goto("/auth/callback?code=11111111-2222-3333-4444-555555555555&state=abc");
  await expect(problem(page)).toHaveAttribute("data-problem", "state");
  expect((await stored(page)).token).toBeNull();

  await page.goto("/auth/callback");
  await expect(page.getByRole("heading", { name: "Nothing to finish here" })).toBeVisible();
  await expect(problem(page)).toHaveAttribute("data-problem", "nothing");
});

test("a sign-in link can't be used twice", async ({ page, context }) => {
  let callback = "";
  page.on("framenavigated", (f) => {
    if (f === page.mainFrame() && f.url().includes("/auth/callback?code=")) callback = f.url();
  });
  await signIn(page);
  await expect(page).toHaveURL(/\/onboarding$/);
  expect(callback).toContain("/auth/callback?code=");
  // the callback is not left in the history: Back does not return to it
  await page.goBack();
  expect(page.url()).not.toContain("/auth/callback");

  // the same link again, in this tab and in a new one
  await page.goto(callback);
  await expect(problem(page)).toHaveAttribute("data-problem", "state");
  const other = await context.newPage();
  await other.goto(callback);
  await expect(other.getByTestId("signin-problem")).toHaveAttribute("data-problem", "state");
});

test("cancelling says so, in plain words", async ({ page }) => {
  await leaveForSignIn(page);
  await choose(page, "cancel");
  await expect(page.getByRole("heading", { name: "Sign-in was cancelled" })).toBeVisible();
  await expect(problem(page)).toHaveText("You left sign-in before it finished. Nothing was changed.");
  expect((await stored(page)).token).toBeNull();
  await expect(page.getByTestId("signin-again")).toHaveText("Sign in again");
});

test("a code that has expired says so", async ({ page, request }) => {
  const asked = await leaveForSignIn(page);
  await choose(page, "slow");
  await expect(page.getByRole("heading", { name: "That sign-in ran out of time" })).toBeVisible();
  await expect(problem(page)).toHaveText("It took too long, or the link was already used. Start again and it will work.");
  const token = (await logFor(request, asked.get("state")!)).filter((e) => e.endpoint === "token");
  expect(token[0].refused).toBe("invalid_grant");
  expect(token[0].why).toBe("code expired");
  expect((await stored(page)).token).toBeNull();
});

test("an account that was not invited says so, and how to ask", async ({ page }) => {
  await leaveForSignIn(page);
  await choose(page, "uninvited");
  await expect(page.getByRole("heading", { name: "That account has not been invited" })).toBeVisible();
  await expect(problem(page)).toHaveText("StEP1 is invite only for now, and this account is not on the list.");
  await expect(page.getByRole("link", { name: "ayertey.narh.24@gmail.com" })).toHaveAttribute("href", /^mailto:/);
  await expect(page.getByTestId("signin-again")).toHaveText("Sign in with another account");
  expect((await stored(page)).token).toBeNull();
});

test.describe("staying signed in", () => {
  test("a token about to run out is renewed before it is used", async ({ page, request }) => {
    const state = await signIn(page, { __ttl: "30" }); // under a minute left: already due
    await expect(page).toHaveURL(/\/onboarding$/);
    const renewals = (await logFor(request, state)).filter((e) => e.grant === "refresh_token");
    expect(renewals.length).toBeGreaterThanOrEqual(1);
    const s = await stored(page);
    expect(claims(s.token!).exp * 1000 - Date.now()).toBeGreaterThan(50 * 60_000); // the renewed one: an hour
    expect(claims(s.token!).nonce).toBeUndefined();
    await onboard(page);
    // no further renewals now that the token is fresh
    expect((await logFor(request, state)).filter((e) => e.grant === "refresh_token")).toHaveLength(renewals.length);
  });

  test("a token the API refuses is renewed and the request repeated, unnoticed", async ({ page, request }) => {
    const state = await signIn(page);
    await onboard(page);
    const before = await stored(page);

    await expireToken(page);
    await page.goto("/applications");
    await expect(page.getByTestId("application-row")).toHaveCount(4);
    await expect(page).toHaveURL(/\/applications$/); // never left the page

    const after = await stored(page);
    expect(after.token).not.toBe(before.token);
    expect(claims(after.token!).exp * 1000).toBeGreaterThan(Date.now());
    expect(after.refresh).toBe(before.refresh); // no rotation: the refresh token stays
    expect((await logFor(request, state)).filter((e) => e.grant === "refresh_token")).toHaveLength(1);
  });

  test("with rotation, the new refresh token replaces the old", async ({ page }) => {
    await signIn(page, { __rotate: "1" });
    await onboard(page);
    const before = await stored(page);
    await expireToken(page);
    await page.goto("/saved");
    await expect(page.getByRole("heading", { name: "Saved" })).toBeVisible();
    await expect(page.getByTestId("posting-card").first()).toBeVisible();
    const after = await stored(page);
    expect(after.refresh).toMatch(/^refresh-/);
    expect(after.refresh).not.toBe(before.refresh);
  });

  test("when it can't be renewed, signing in again returns to the same page", async ({ page }) => {
    await signIn(page, { __refresh: "fail" });
    await onboard(page);
    await expireToken(page);

    await page.goto("/?roles=security&sort=score");
    await expect(page).toHaveURL(/\/login\?expired=1$/);
    await expect(page.getByTestId("expired-notice")).toHaveText(
      "Your session expired. Sign in again and you will be back where you were."
    );
    expect((await stored(page)).token).toBeNull();

    await page.getByTestId("cognito-sign-in").click();
    await page.waitForURL(`${STUB}/oauth2/authorize**`);
    await choose(page, "invited");
    await expect(page).toHaveURL(/\/\?roles=security&sort=score$/);
    await expect(page.getByTestId("posting-card")).toHaveCount(4);
    await expect(page.getByRole("radio", { name: "Best match" })).toBeChecked();
  });

  test("a signed-out deep link comes back to that page after signing in", async ({ page }) => {
    await signIn(page);
    await onboard(page);
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);

    await page.goto("/application?id=12");
    await expect(page).toHaveURL(/\/login$/);
    await page.getByTestId("cognito-sign-in").click();
    await page.waitForURL(`${STUB}/oauth2/authorize**`);
    await choose(page, "invited");
    await expect(page).toHaveURL(/\/application\?id=12$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Software Development Intern");
  });

  test("a return address that leaves the site is ignored", async ({ page }) => {
    await signIn(page);
    await onboard(page);
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await page.evaluate(() => sessionStorage.setItem("step1.returnTo", "//evil.example/steal"));
    await page.getByTestId("cognito-sign-in").click();
    await page.waitForURL(`${STUB}/oauth2/authorize**`);
    await choose(page, "invited");
    await expect(page).toHaveURL(new RegExp(`^http://localhost:${SITE.port}/$`));
  });
});

test("signing out ends the session here and at the sign-in service", async ({ page, request }) => {
  await signIn(page);
  await expect(page).toHaveURL(/\/onboarding$/);
  const seen: string[] = [];
  page.on("request", (r) => {
    if (r.isNavigationRequest()) seen.push(r.url());
  });
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  const logout = seen.find((u) => u.startsWith(`${STUB}/logout`));
  expect(logout, "the browser went through the sign-out endpoint").toBeTruthy();
  const q = new URL(logout!).searchParams;
  expect(q.get("client_id")).toBe(OIDC.client);
  expect(q.get("logout_uri")).toBe(SITE.env.NEXT_PUBLIC_COGNITO_LOGOUT_URI);
  expect((await (await request.get(`${STUB}/__test/log`)).json()).some((e: Entry) => e.endpoint === "logout")).toBe(true);

  const s = await stored(page);
  expect(s).toEqual({ token: null, refresh: null, expires: 0, user: null });
  await page.goto("/saved");
  await expect(page).toHaveURL(/\/login$/);
});

test("delete my account asks for no password, keeps the typed confirmation", async ({ page }) => {
  await signIn(page);
  await onboard(page);
  await page.goto("/onboarding");
  await page.getByTestId("open-delete").click();
  const dialog = page.getByRole("dialog", { name: "Delete your account?" });
  await expect(dialog.locator('input[type="password"]')).toHaveCount(0);
  await expect(dialog.getByText("password", { exact: false })).toHaveCount(0);
  const word = dialog.getByLabel("Type DELETE to confirm");
  await expect(word).toBeFocused();
  const confirm = dialog.getByTestId("confirm-delete");

  await dialog.getByRole("checkbox").check();
  await expect(confirm).toBeDisabled(); // the box alone is not enough
  await word.fill("remove");
  await expect(confirm).toBeDisabled();
  await word.fill("delete"); // any case
  await expect(confirm).toBeEnabled();
  await dialog.getByRole("checkbox").uncheck();
  await expect(confirm).toBeDisabled(); // the word alone is not enough
  await dialog.getByRole("checkbox").check();
  await expectAccessible(page, "delete dialog, cognito mode");

  const seen: string[] = [];
  page.on("request", (r) => {
    if (r.isNavigationRequest()) seen.push(r.url());
  });
  await confirm.click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByTestId("deleted-notice")).toHaveText("Your account and everything in it have been deleted.");
  expect(seen.some((u) => u.startsWith(`${STUB}/logout`))).toBe(true);
  expect((await stored(page)).token).toBeNull();

  // the message is shown once
  await page.reload();
  await expect(page.getByTestId("deleted-notice")).toHaveCount(0);

  // the same person signing in again starts from nothing
  await signIn(page);
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByLabel("Major")).toHaveValue("");
});

test("two people on one browser don't see each other's things", async ({ page }) => {
  await signIn(page);
  await onboard(page);
  const card = page.getByTestId("posting-card").filter({ has: page.getByTestId("apply-button") }).first();
  const id = await card.getAttribute("data-posting-id");
  await card.getByTestId("apply-button").click();
  await page.getByTestId("confirm-applied").click();
  await expect(page.locator(`[data-posting-id="${id}"]`).getByTestId("application-link")).toBeVisible();
  await page.goto("/applications");
  await expect(page.getByTestId("application-row")).toHaveCount(5);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login$/);

  await signIn(page, {}, "second");
  await expect(page).toHaveURL(/\/onboarding$/);
  expect((await stored(page)).user.email).toBe("second@umd.edu");
  await onboard(page);
  await page.goto("/applications");
  await expect(page.getByTestId("application-row")).toHaveCount(4); // the starting four, not the first person's five
});

for (const scheme of ["light", "dark"] as const) {
  test(`the sign-in and error screens are accessible (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/login");
    await expect(page.getByTestId("cognito-sign-in")).toBeVisible();
    await expectAccessible(page, "sign in");

    await page.goto("/login?expired=1");
    await expect(page.getByTestId("expired-notice")).toBeVisible();
    await expectAccessible(page, "sign in, after the session expired");

    for (const [as, title] of [
      ["cancel", "Sign-in was cancelled"],
      ["forged-state", "Sign-in was stopped"],
      ["slow", "That sign-in ran out of time"],
      ["uninvited", "That account has not been invited"],
    ] as const) {
      await leaveForSignIn(page);
      await choose(page, as);
      await expect(page.getByRole("heading", { name: title })).toBeVisible();
      await expectAccessible(page, title);
      const box = await page.evaluate(() => ({
        page: document.documentElement.scrollWidth,
        view: document.documentElement.clientWidth,
      }));
      expect(box.page, `${title}: no sideways scroll`).toBeLessThanOrEqual(box.view);
      expect(await page.locator("body").innerText(), title).not.toContain("—");
    }

    await page.goto("/auth/callback");
    await expect(page.getByRole("heading", { name: "Nothing to finish here" })).toBeVisible();
    await expectAccessible(page, "callback with nothing to do");
  });
}
