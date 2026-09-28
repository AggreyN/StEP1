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

    await signInDemo(page);
    await shot("dashboard");

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
