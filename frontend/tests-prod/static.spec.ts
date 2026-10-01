// The exported site, served as plain files with the Amplify rewrite rules
// and the security headers. Local sign-in, mock API.
import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { SITES } from "./support/sites.mjs";
import { metaPolicy, securityHeaders } from "../security-headers.mjs";
import { PASSWORD, freshEmail, pdfFile } from "../tests/helpers";

const SITE = SITES.local;
test.use({ baseURL: `http://localhost:${SITE.port}` });

const OUT = path.resolve(__dirname, "..", SITE.dir);
const DEMO = "demo@umd.edu";

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

/** Collects Content-Security-Policy violations and page errors. */
function watch(page: Page): string[] {
  const found: string[] = [];
  page.on("console", (m) => {
    if (/Content Security Policy|Content-Security-Policy/i.test(m.text())) found.push(`console: ${m.text()}`);
  });
  page.on("pageerror", (e) => found.push(`page error: ${e.message}`));
  return found;
}

async function signIn(page: Page, email = DEMO) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
}

async function signInDemo(page: Page) {
  await signIn(page);
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("posting-card").first()).toBeVisible();
}

test.describe("the files", () => {
  test("every page is a file, with a real 404 page", () => {
    for (const file of [
      "index.html",
      "login.html",
      "auth/callback.html",
      "onboarding.html",
      "onboarding/building.html",
      "saved.html",
      "applications.html",
      "application.html",
      "about.html",
      "privacy.html",
      "review.html",
      "admin.html",
      "admin/user.html",
      "resume.html",
      "tailor.html",
      "resumes.html",
      "resumes/edit.html",
      "404.html",
      "icon.svg",
    ]) {
      expect(statSync(path.join(OUT, file)).isFile(), file).toBe(true);
    }
  });

  test("fonts are in the export, and nothing is loaded from another site", () => {
    const files = walk(OUT);
    const fonts = files.filter((f) => f.endsWith(".woff2"));
    expect(fonts.length).toBeGreaterThanOrEqual(3); // Plex Sans, Source Serif 4, Plex Mono

    const css = files.filter((f) => f.endsWith(".css")).map((f) => readFileSync(f, "utf8")).join("\n");
    for (const family of ["IBM Plex Sans", "Source Serif 4", "IBM Plex Mono"]) expect(css).toContain(family);
    const urls = [...css.matchAll(/url\(([^)]+)\)/g)].map((m) => m[1].replace(/["']/g, ""));
    expect(urls.length).toBeGreaterThan(0);
    for (const u of urls) expect(u, "a stylesheet url()").toMatch(/^(\/_next\/|\.\.?\/|data:)/);

    for (const f of files.filter((x) => /\.(html|css|js)$/.test(x))) {
      const text = readFileSync(f, "utf8");
      expect(text, path.relative(OUT, f)).not.toMatch(/fonts\.(googleapis|gstatic)\.com/);
    }
  });

  test("every page carries the policy for this build's exact origins", () => {
    const expected = metaPolicy({ NODE_ENV: "production", NEXT_PUBLIC_API_BASE: "mock" });
    expect(expected).toContain("connect-src 'self';");
    expect(expected).not.toContain("frame-ancestors"); // not allowed in a <meta> tag; the header has it
    const pages = walk(OUT).filter((f) => f.endsWith(".html"));
    expect(pages.length).toBeGreaterThanOrEqual(19);
    for (const f of pages) {
      const html = readFileSync(f, "utf8").replace(/&#x27;/g, "'");
      expect(html, path.relative(OUT, f)).toContain(`http-equiv="Content-Security-Policy" content="${expected}"`);
    }
  });
});

test.describe("what the host sends", () => {
  test("the security headers, on pages, assets and the 404", async ({ request }) => {
    const expected = securityHeaders({ dev: false });
    const csp = expected.find((h) => h.key === "Content-Security-Policy")!.value;
    expect(csp).toBe(
      "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self'; img-src 'self' data:; " +
        "font-src 'self'; connect-src 'self' https:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    );
    for (const p of ["/", "/login", "/about", "/application?id=12", "/icon.svg", "/no-such-page"]) {
      const res = await request.get(p, { maxRedirects: 0 });
      for (const h of expected) expect(res.headers()[h.key.toLowerCase()], `${h.key} on ${p}`).toBe(h.value);
    }
  });

  test("the favicon", async ({ page, request }) => {
    const res = await request.get("/icon.svg");
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("image/svg+xml");
    expect(await res.text()).toContain("#6f4325");
    await page.goto("/about");
    const href = await page.locator('link[rel="icon"]').first().getAttribute("href");
    expect(href).toMatch(/^\/icon\.svg/);
    expect((await request.get(href!)).status()).toBe(200);
  });

  test("an unknown address gets the 404 page with a 404 status", async ({ page }) => {
    const found = watch(page);
    const res = await page.goto("/no/such/page?x=1");
    expect(res!.status()).toBe(404);
    await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
    await expect(page).toHaveURL(/\/no\/such\/page\?x=1$/); // the address is left alone
    await page.getByRole("link", { name: "About StEP1" }).click();
    await expect(page).toHaveURL(/\/about$/);
    expect(found).toEqual([]);
  });
});

test.describe("deep links", () => {
  test("public pages load directly and survive a reload, signed out", async ({ page }) => {
    const found = watch(page);
    for (const [url, heading] of [
      ["/login", "Sign in"],
      ["/about", "I kept losing track of my own applications."],
      ["/privacy", "What StEP1 keeps about you, and what it doesn't."],
    ] as const) {
      const res = await page.goto(url);
      expect(res!.status(), url).toBe(200);
      await expect(page.getByRole("heading", { level: 1 }), url).toHaveText(heading);
      await page.reload();
      await expect(page.getByRole("heading", { level: 1 }), url).toHaveText(heading);
      await expect(page, url).toHaveURL(new RegExp(`${url}$`));
    }
    expect(found).toEqual([]);
  });

  test("signed-in pages send a signed-out visitor to sign in", async ({ page }) => {
    for (const url of ["/", "/saved", "/applications", "/application?id=12", "/onboarding", "/onboarding/building", "/review", "/admin", "/admin?tab=users", "/admin/user?id=1", "/resume", "/tailor", "/resumes", "/resumes/edit?id=1"]) {
      const res = await page.goto(url);
      expect(res!.status(), url).toBe(200); // the file exists; the page itself asks for sign-in
      await expect(page, url).toHaveURL(/\/login$/);
    }
  });

  test("every signed-in page loads directly and survives a reload", async ({ page }) => {
    const found = watch(page);
    await signInDemo(page);
    const pages: [string, () => Promise<void>][] = [
      ["/", async () => expect(page.getByTestId("posting-card").first()).toBeVisible()],
      ["/saved", async () => expect(page.getByRole("heading", { name: "Saved" })).toBeVisible()],
      ["/applications", async () => expect(page.getByTestId("application-row")).toHaveCount(4)],
      ["/application?id=12", async () => expect(page.getByRole("heading", { level: 1 })).toHaveText("Software Development Intern")],
      ["/application?id=9", async () => expect(page.locator('[data-testid="timeline-event"][data-kind="ghosted"]')).toBeVisible()],
      ["/onboarding", async () => expect(page.getByLabel("Major")).toHaveValue("Information Science")],
      ["/review", async () => expect(page.getByRole("radio", { name: "5 stars" })).toBeVisible()],
      ["/admin", async () => expect(page.getByTestId("admin-review").first()).toBeVisible()],
      ["/admin?tab=users", async () => expect(page.getByTestId("person-row").first()).toBeVisible()],
      ["/admin/user?id=1", async () => expect(page.getByTestId("viewing-banner")).toBeVisible()],
      ["/resume", async () => expect(page.getByTestId("base-empty")).toBeVisible()],
      ["/tailor", async () => expect(page.getByTestId("job-text")).toBeVisible()],
      ["/resumes", async () => expect(page.getByTestId("resumes-empty")).toBeVisible()],
    ];
    for (const [url, ready] of pages) {
      const res = await page.goto(url);
      expect(res!.status(), url).toBe(200);
      await ready();
      await page.reload();
      await ready();
      expect(page.url().replace(/^https?:\/\/[^/]+/, ""), url).toBe(url);
    }

    await page.evaluate(() => localStorage.setItem("step1.mock.stuck", "1"));
    await page.goto("/onboarding/building?retry=1");
    await expect(page.getByTestId("building-step")).toHaveText("Scanning 4,139 open internships");
    await page.reload();
    await expect(page.getByTestId("building-step")).toHaveText("Scanning 4,139 open internships");
    await expect(page).toHaveURL(/\/onboarding\/building\?retry=1$/);
    expect(found).toEqual([]);
  });

  test("filters and sort in the address survive a direct load and a reload", async ({ page }) => {
    await signInDemo(page);
    const url = "/?roles=security&min_score=80&term=Summer+2027&remote=true&sort=score";
    await page.goto(url);
    const check = async () => {
      await expect(page.getByTestId("feed-total")).toHaveText("1 posting matches your filters, best match first");
      await expect(page.getByTestId("posting-card")).toHaveCount(1);
      await expect(page.getByTestId("posting-card").first()).toContainText("CrowdStrike");
      await expect(page.getByRole("radio", { name: "Best match" })).toBeChecked();
    };
    await check();
    await page.reload();
    await check();
    expect(page.url().endsWith(url)).toBe(true);

    await page.goto("/?roles=security&location=Seattle");
    await expect(page.getByTestId("empty-state")).toContainText("No Security postings in Seattle.");
    await page.getByTestId("relax-location").click();
    await expect(page).toHaveURL(/\/\?roles=security$/);
    await page.reload();
    await expect(page.getByTestId("posting-card")).toHaveCount(4);
  });

  test("old-style /applications/12 links still reach the timeline", async ({ page }) => {
    await signInDemo(page);
    for (const old of ["/applications/12", "/applications/12/"]) {
      await page.goto(old);
      await expect(page, old).toHaveURL(/\/application\?id=12$/);
      await expect(page.getByRole("heading", { level: 1 }), old).toHaveText("Software Development Intern");
      await expect(page.getByTestId("timeline-event")).toHaveCount(3);
    }
    // an id that doesn't exist says so, through the API's own message
    await page.goto("/applications/99999");
    await expect(page).toHaveURL(/\/application\?id=99999$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Application not found");
    // the list itself is not mistaken for an old-style link
    await page.goto("/applications");
    await expect(page).toHaveURL(/\/applications$/);
    await expect(page.getByTestId("application-row")).toHaveCount(4);
  });

  test("a stray trailing slash or .html still reaches the page", async ({ page }) => {
    await page.goto("/about/");
    await expect(page).toHaveURL(/\/about$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("I kept losing track of my own applications.");
    await page.goto("/privacy.html");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("What StEP1 keeps about you, and what it doesn't.");
  });

  test("moving between pages inside the site needs no server", async ({ page }) => {
    const found = watch(page);
    const failed: string[] = [];
    page.on("response", (r) => {
      if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`);
    });
    await signInDemo(page);
    const nav = page.getByRole("navigation", { name: "Main" });
    await nav.getByRole("link", { name: "Saved" }).click();
    await expect(page).toHaveURL(/\/saved$/);
    await nav.getByRole("link", { name: "Applications" }).click();
    await expect(page).toHaveURL(/\/applications$/);
    await page.getByTestId("application-row").first().click();
    await expect(page).toHaveURL(/\/application\?id=\d+$/);
    await expect(page.getByTestId("timeline")).toBeVisible();
    await page.getByRole("link", { name: "← All applications" }).click();
    await expect(page).toHaveURL(/\/applications$/);
    await page.goBack();
    await expect(page).toHaveURL(/\/application\?id=\d+$/);
    await expect(page.getByTestId("timeline")).toBeVisible();
    await page.getByRole("contentinfo").getByRole("link", { name: "Privacy" }).click();
    await expect(page).toHaveURL(/\/privacy$/);
    expect(failed).toEqual([]);
    expect(found).toEqual([]);
  });
});

test("the whole journey works from files, with no policy violations", async ({ page }, info) => {
  const found = watch(page);
  await page.addInitScript(() => {
    const w = window as unknown as { __csp: string[] };
    w.__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => {
      w.__csp.push(`${e.violatedDirective} blocked ${e.blockedURI || "inline"} on ${location.pathname}`);
    });
  });
  let screens = 0;
  const check = async (screen: string) => {
    screens++;
    expect(await page.evaluate(() => (window as unknown as { __csp?: string[] }).__csp ?? []), screen).toEqual([]);
    expect(found, screen).toEqual([]);
  };

  await page.goto("/about");
  await expect(page.getByTestId("stat-active_postings")).toHaveText("4,769");
  await check("about");

  await page.goto("/login");
  await page.getByRole("tab", { name: "Register" }).click();
  await page.getByLabel("Email").fill(freshEmail("static"));
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await check("login");

  await page.getByLabel("Major").fill("Information Science");
  for (const n of ["+ Security", "+ Software Engineering", "+ Research"]) {
    await page.getByRole("button", { name: n }).click();
  }
  await page.getByRole("button", { name: "Move Research up" }).click();
  await page.locator("#resume-file").setInputFiles(pdfFile());
  await expect(page.getByRole("list", { name: "Extracted skills" })).toBeVisible();
  await check("onboarding");

  await page.getByTestId("submit-profile").click();
  await expect(page).toHaveURL(/\/onboarding\/building/);
  await expect(page.getByRole("progressbar")).toBeVisible();
  await check("building");

  await expect(page).toHaveURL(/\/$/, { timeout: 15_000 });
  await expect(page.getByTestId("posting-card").first()).toBeVisible();
  await expect(page.getByTestId("freshness")).toBeVisible();
  await page.getByRole("radio", { name: "Best match" }).click();
  await expect(page).toHaveURL(/sort=score/);
  await page.getByTestId("load-more").click();
  await expect(page.getByTestId("posting-card")).toHaveCount(40);
  if (info.project.name === "mobile") {
    await page.getByTestId("open-filters").click();
    await page.getByRole("checkbox", { name: "Security" }).check();
    await check("filter sheet");
    await page.getByTestId("close-filters").click();
  } else {
    await page.getByRole("checkbox", { name: "Security" }).check();
  }
  await expect(page).toHaveURL(/roles=security/);
  await check("dashboard");

  await page.goto("/");
  const card = page.getByTestId("posting-card").filter({ has: page.getByTestId("apply-button") }).first();
  const id = await card.getAttribute("data-posting-id");
  const mine = page.locator(`[data-posting-id="${id}"]`);
  await mine.getByTestId("save-toggle").click();
  await mine.getByTestId("apply-button").click();
  await page.getByTestId("confirm-applied").click();
  await mine.getByTestId("application-link").click();

  await expect(page).toHaveURL(/\/application\?id=\d+$/);
  await expect(page.getByTestId("timeline-event")).toHaveCount(1);
  await page.getByTestId("transition-button").first().click();
  await page.getByPlaceholder("Who you spoke to").fill("Recorded on the static site");
  await page.getByTestId("save-event").click();
  await expect(page.getByTestId("timeline")).toContainText("Recorded on the static site");
  await page.reload();
  await expect(page.getByTestId("timeline")).toContainText("Recorded on the static site");
  await check("timeline");

  await page.goto("/saved");
  await expect(page.locator(`[data-posting-id="${id}"]`)).toBeVisible();
  await check("saved");
  await page.goto("/applications");
  await expect(page.getByTestId("application-row").first()).toBeVisible();
  await check("applications");

  await page.goto("/onboarding");
  await page.getByTestId("open-delete").click();
  await page.getByLabel("Your password").fill(PASSWORD);
  await page.getByRole("dialog").getByRole("checkbox").check();
  await page.getByTestId("confirm-delete").click();
  await expect(page).toHaveURL(/\/login\?deleted=1$/);
  await expect(page.getByTestId("deleted-notice")).toBeVisible();
  await check("after deletion");
  expect(screens).toBeGreaterThanOrEqual(9);
});

test("the policy is enforced: a foreign request, an image beacon, eval and an inline style are all blocked", async ({
  page,
}) => {
  await page.goto("/about");
  await expect(page.getByTestId("stat-active_postings")).toHaveText("4,769");
  const result = await page.evaluate(async () => {
    const out: Record<string, string> = {};
    try {
      // allowed by the header (any HTTPS), refused by the page's own, exact policy
      await fetch("https://example.com/collect?t=secret", { mode: "no-cors" });
      out.fetch = "sent";
    } catch {
      out.fetch = "blocked";
    }
    out.image = await new Promise<string>((resolve) => {
      const img = new Image();
      img.onload = () => resolve("loaded");
      img.onerror = () => resolve("blocked");
      img.src = "https://example.com/pixel.gif?t=secret";
      setTimeout(() => resolve("blocked"), 3000);
    });
    try {
      out.eval = String((0, eval)("1 + 1"));
    } catch {
      out.eval = "blocked";
    }
    const probe = document.createElement("div");
    probe.setAttribute("style", "position: fixed");
    document.body.append(probe);
    out.inlineStyle = getComputedStyle(probe).position === "fixed" ? "applied" : "blocked";
    probe.remove();
    return out;
  });
  expect(result).toEqual({ fetch: "blocked", image: "blocked", eval: "blocked", inlineStyle: "blocked" });
});

test("the site can't be framed", async ({ request }) => {
  const res = await request.get("/login");
  expect(res.headers()["x-frame-options"]).toBe("DENY");
  expect(res.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
});

test("a review can be sent from the exported site, and the admin page reads it", async ({ page }) => {
  await signInDemo(page);
  await page.goto("/review");
  await page.getByRole("radio", { name: "4 stars" }).click();
  await page.getByRole("textbox", { name: "Your review" }).fill("Sent from the static site.");
  await page.getByTestId("send-review").click();
  await expect(page.getByTestId("review-sent")).toBeVisible();
  await page.goto("/admin");
  await expect(page.getByTestId("admin-review").first()).toContainText("Sent from the static site.");
  await page.reload();
  await expect(page.getByTestId("admin-review").first()).toContainText("Sent from the static site.");
});

test("a non-admin deep-linking to /admin gets the not-found page", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("tab", { name: "Register" }).click();
  await page.getByLabel("Email").fill(freshEmail("notadmin"));
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
});

test("tailoring works from the exported site: base, tailor, save, reopen, download", async ({ page }) => {
  await signInDemo(page);
  await page.goto("/resume");
  await page.getByTestId("extract-base").click();
  await page.getByTestId("save-base").click();
  await expect(page.getByTestId("base-status")).toHaveText("Saved.");
  await page.goto("/");
  await page.getByTestId("posting-card").first().getByTestId("tailor-button").click();
  await expect(page).toHaveURL(/\/tailor\?posting=/);
  await expect(page.getByTestId("tailor-report")).toBeVisible({ timeout: 15_000 });
  await page.reload(); // a reload of /tailor?posting= runs it again
  await expect(page.getByTestId("tailor-report")).toBeVisible({ timeout: 15_000 });
  await page.getByTestId("save-tailored").click();
  await expect(page.getByTestId("tailored-status")).toContainText("Saved.");
  await page.goto("/resumes");
  await page.getByRole("link", { name: /^Open / }).click();
  await expect(page).toHaveURL(/\/resumes\/edit\?id=\d+$/);
  await page.reload();
  await expect(page.getByTestId("resume-editor")).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByTestId("download-pdf").click();
  expect((await download).suggestedFilename()).toMatch(/^Jordan_Ellis_.+\.pdf$/);
});
