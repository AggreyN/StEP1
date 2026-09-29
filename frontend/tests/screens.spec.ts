// Optional: writes screenshots of the main screens for a visual check.
//   SCREENSHOT_DIR=/some/dir npx playwright test screens
// Skipped unless SCREENSHOT_DIR is set.
import path from "node:path";
import { expect, test } from "@playwright/test";
import { signInDemo } from "./helpers";

const DIR = process.env.SCREENSHOT_DIR;
test.skip(!DIR, "set SCREENSHOT_DIR to capture screenshots");

for (const scheme of ["light", "dark"] as const) {
  test(`screens (${scheme})`, async ({ page }, info) => {
    const shot = (name: string, fullPage = false) =>
      page.screenshot({ path: path.join(DIR!, `${info.project.name}-${name}-${scheme}.png`), fullPage });
    await page.emulateMedia({ colorScheme: scheme });

    await page.goto("/login", { waitUntil: "networkidle" });
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
    await shot("login");

    await page.getByRole("tab", { name: "Register" }).click();
    await shot("register");

    await page.goto("/about", { waitUntil: "networkidle" });
    await expect(page.getByTestId("stat-active_postings")).toHaveText("4,769");
    await shot("about-top");
    await shot("about", true);

    await page.goto("/privacy", { waitUntil: "networkidle" });
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await shot("privacy", true);

    await signInDemo(page);
    await expect(page.getByTestId("freshness")).toBeVisible();
    await shot("dashboard");

    await page.getByRole("radio", { name: "Best match" }).click();
    await expect(page.getByTestId("feed-total")).toContainText("best match first");
    await expect(page.getByTestId("posting-card").first()).toBeVisible();
    await shot("dashboard-best-match");
    await page.getByRole("radio", { name: "Newest first" }).click();

    for (const scenario of ["failed", "running"]) {
      await page.evaluate((v) => localStorage.setItem("step1.mock.ingest", v), scenario);
      await page.reload();
      await expect(page.getByTestId("freshness")).toBeVisible();
      await expect(page.getByTestId("posting-card").first()).toBeVisible();
      await shot(`dashboard-listings-${scenario}`);
    }
    await page.evaluate(() => localStorage.removeItem("step1.mock.ingest"));
    await page.reload();
    await expect(page.getByTestId("posting-card").first()).toBeVisible();

    if (info.project.name === "mobile") {
      await page.getByTestId("open-filters").click();
      await expect(page.getByRole("checkbox", { name: "Security" })).toBeVisible();
      await shot("filters-sheet");
      await page.getByTestId("close-filters").click();
    }

    await page.goto("/?roles=security&location=Seattle");
    await expect(page.getByTestId("relaxations")).toBeVisible();
    await shot("empty-state");

    await page.goto("/onboarding");
    await expect(page.getByTestId("ranked-interest").first()).toBeVisible();
    await shot("onboarding-top");
    await shot("onboarding", true);
    await page.getByTestId("open-delete").click();
    await expect(page.getByTestId("confirm-delete")).toBeVisible();
    await shot("delete-dialog");
    await page.getByRole("button", { name: "Keep my account" }).click();

    await page.evaluate(() => localStorage.setItem("step1.mock.stuck", "1"));
    await page.goto("/onboarding/building?retry=1");
    await expect(page.getByTestId("building-step")).toHaveText("Scanning 4,139 open internships");
    await shot("building");
    await page.evaluate(() => localStorage.removeItem("step1.mock.stuck"));

    await page.goto("/saved");
    await expect(page.getByTestId("posting-card").first()).toBeVisible();
    await shot("saved");

    await page.goto("/applications");
    await expect(page.getByTestId("application-row").first()).toBeVisible();
    await shot("applications");

    await page.goto("/applications/12");
    await expect(page.getByTestId("timeline")).toBeVisible();
    await shot("timeline", true);
    await page.getByTestId("transition-button").first().click();
    await expect(page.getByTestId("save-event")).toBeVisible();
    await shot("timeline-dialog");
    await page.getByRole("button", { name: "Cancel" }).click();

    await page.goto("/applications/9");
    await expect(page.getByTestId("timeline")).toBeVisible();
    await shot("timeline-ghosted", true);
  });
}
