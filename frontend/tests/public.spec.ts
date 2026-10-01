// The two public pages, and the footer that links to them from everywhere.
import { expect, test, type Page } from "@playwright/test";
import { expectNoHorizontalScroll, signInDemo } from "./helpers";

const requests = (page: Page) =>
  page.evaluate(() => (window as unknown as { __step1Requests?: string[] }).__step1Requests ?? []);

test.describe("About", () => {
  test("is public, and shows real numbers from the API, flat", async ({ page }) => {
    await page.goto("/about");
    await expect(page).toHaveURL(/\/about$/); // no redirect to /login
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("I kept losing track of my own applications.");

    // space is reserved while loading, with no made-up numbers in it
    const stats = page.getByTestId("about-stats");
    await expect(stats).toBeVisible();
    const loadingBox = await stats.boundingBox();

    await expect(page.getByTestId("stat-active_postings")).toHaveText("4,769");
    await expect(page.getByTestId("stat-companies")).toHaveText("1,241");
    await expect(page.getByTestId("stat-role_families")).toHaveText("15");
    const loadedBox = await stats.boundingBox();
    expect(Math.abs(loadedBox!.height - loadingBox!.height)).toBeLessThan(1); // nothing jumped

    // flat: the text never changes once shown (no count-up)
    const seen = new Set<string>();
    for (let i = 0; i < 10; i++) {
      seen.add(await page.getByTestId("stat-active_postings").innerText());
      await page.waitForTimeout(60);
    }
    expect([...seen]).toEqual(["4,769"]);

    // only the public stats call was made: none of the signed-in data calls
    // (the dev server mounts effects twice, so the one call can appear twice)
    const made = await requests(page);
    expect(made.length).toBeGreaterThanOrEqual(1);
    expect(made.every((r) => r === "GET /stats")).toBe(true);
    expect(await page.evaluate(() => localStorage.getItem("step1.token"))).toBeNull();
  });

  test("while loading it shows no numbers at all", async ({ page }) => {
    await page.goto("/about", { waitUntil: "commit" });
    const value = page.getByTestId("stat-active_postings");
    await expect(value).toBeVisible();
    const first = (await value.innerText()).trim();
    expect(first === "" || first === "4,769").toBe(true); // blank, never a placeholder number
    await expect(value).toHaveText("4,769");
  });

  test("leaves the stats row out when the API call fails", async ({ page }) => {
    await page.goto("/privacy");
    await page.evaluate(() => localStorage.setItem("step1.mock.fail", "always GET /stats"));
    await page.goto("/about");
    await expect.poll(() => requests(page)).toContain("GET /stats");
    await expect(page.getByTestId("about-stats")).toHaveCount(0);
    await expect(page.getByText("Active postings")).toHaveCount(0);
    // the rest of the page is untouched
    await expect(page.getByText("The scoring is a weighted sum, not a black box.")).toBeVisible();
    await expect(page.locator('[role="alert"]:not(#__next-route-announcer__)')).toHaveCount(0);
  });

  test("copy: only claims what is built, has no em dashes, one card, no images", async ({ page }) => {
    await page.goto("/about");
    const main = page.getByRole("main");
    await expect(main).toContainText(
      "StEP1 pulls from community-maintained internship and new grad boards, then classifies every posting by role and scores it against your profile."
    );
    await expect(main).not.toContainText("federal job listings");
    await expect(main).not.toContainText("public job APIs");
    await expect(page.getByTestId("stat-active_postings")).toHaveText("4,769");
    const text = await page.locator("body").innerText();
    expect(text).not.toContain("—");
    expect(await page.locator("img, picture, video, canvas").count()).toBe(0);
    await expect(page.getByRole("link", { name: "Contact me" })).toHaveAttribute(
      "href",
      /^mailto:ayertey\.narh\.24@gmail\.com\?subject=StEP1&body=/
    );
    await expect(main.getByRole("link", { name: "privacy policy" })).toHaveAttribute("href", "/privacy");
  });

  test("the email can be copied", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.goto("/about");
    await page.getByRole("button", { name: "Copy" }).click();
    await expect(page.getByRole("button", { name: "Copied" })).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("ayertey.narh.24@gmail.com");
    await expect(page.getByRole("button", { name: "Copy" })).toBeVisible({ timeout: 4000 });
  });
});

test.describe("Privacy", () => {
  test("is public, makes no API calls, and says what the app does", async ({ page }) => {
    await page.goto("/privacy");
    await expect(page).toHaveURL(/\/privacy$/);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    const main = page.getByRole("main");
    for (const phrase of [
      "a hash of your password. The password itself is never stored.",
      "ranked fields of interest",
      "the file, plus the text and the skills read from it",
      "the events and notes on each one",
      "No analytics, no tracking, no ads, and no cookies.",
      "browser's local storage",
      "Nothing is sold, and nothing is shared with anyone.",
      "The hosted site runs on Amazon Web Services in the United States.",
      "Resumes sit in a private, encrypted storage bucket and are never public.",
      "The database is encrypted at rest.",
      "I'm Aggrey Narh and I run the site. Nobody else can.",
      "It is not a model trained on your data",
      "Every listing links to the original posting",
      "Go to Profile, then Delete my account.",
      "ayertey.narh.24@gmail.com",
      "Last updated",
    ]) {
      await expect(main).toContainText(phrase);
    }
    const text = await page.locator("body").innerText();
    expect(text).not.toContain("—");
    // about half a page
    const words = (await main.innerText()).split(/\s+/).filter(Boolean).length;
    expect(words).toBeGreaterThan(200);
    expect(words).toBeLessThan(420);
    expect(await requests(page)).toEqual([]);
  });
});

test("both public pages share the prose typography", async ({ page }) => {
  const faces: string[] = [];
  for (const path of ["/about", "/privacy"]) {
    await page.goto(path);
    const f = await page.evaluate(() => ({
      body: getComputedStyle(document.querySelector("main p")!).fontFamily,
      label: getComputedStyle(document.querySelector("main h2")!).fontFamily,
    }));
    expect(f.body).toContain("Source Serif 4");
    expect(f.label).toContain("IBM Plex Sans");
    faces.push(JSON.stringify(f));
  }
  expect(faces[0]).toBe(faces[1]);
  await page.goto("/about");
  await expect(page.getByTestId("stat-companies")).toHaveText("1,241");
  expect(await page.getByTestId("stat-companies").evaluate((el) => getComputedStyle(el).fontFamily)).toContain(
    "IBM Plex Mono"
  );
});

test("the footer links to About and Privacy on every screen, signed in or out", async ({ page }) => {
  const check = async (path: string) => {
    await page.goto(path);
    const footer = page.getByRole("contentinfo");
    await expect(footer.getByRole("link", { name: "About" }), path).toHaveAttribute("href", "/about");
    await expect(footer.getByRole("link", { name: "Privacy" }), path).toHaveAttribute("href", "/privacy");
    await expect(footer, path).toContainText("SimplifyJobs");
  };
  for (const path of ["/login", "/about", "/privacy"]) await check(path);
  await signInDemo(page);
  for (const path of ["/", "/saved", "/applications", "/application?id=12", "/onboarding"]) await check(path);

  await page.getByRole("contentinfo").getByRole("link", { name: "Privacy" }).click();
  await expect(page).toHaveURL(/\/privacy$/);
  await page.getByRole("contentinfo").getByRole("link", { name: "About" }).click();
  await expect(page).toHaveURL(/\/about$/);
});

test.describe("at 375px", () => {
  test.use({ viewport: { width: 375, height: 812 } });
  test("About and Privacy fit", async ({ page }) => {
    await page.goto("/about");
    await expect(page.getByTestId("stat-active_postings")).toHaveText("4,769");
    await expectNoHorizontalScroll(page);
    await page.goto("/privacy");
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectNoHorizontalScroll(page);
  });
});
