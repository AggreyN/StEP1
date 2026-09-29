// axe on every screen, in light and dark, at desktop width and at 375px
// (this file runs in both Playwright projects). Any violation fails.
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { signInDemo } from "./helpers";

async function expectNoViolations(page: Page, screen: string) {
  // let fonts and any late render settle, so contrast is measured on the final paint
  await page.evaluate(() => document.fonts.ready);
  const { violations } = await new AxeBuilder({ page }).analyze();
  const report = violations.map((v) => ({
    rule: v.id,
    impact: v.impact,
    help: v.help,
    nodes: v.nodes.slice(0, 5).map((n) => ({ target: n.target.join(" "), why: n.failureSummary?.split("\n").slice(0, 4).join(" ") })),
  }));
  expect(report, `${screen}: accessibility violations`).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.beforeEach(async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
    });

    test("public screens: sign in, register, About, Privacy", async ({ page }) => {
      await page.goto("/login");
      await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
      await expectNoViolations(page, "login");

      await page.getByRole("tab", { name: "Register" }).click();
      await page.getByLabel("Password").fill("short");
      await page.getByLabel("Email").fill("someone@umd.edu");
      await page.getByRole("button", { name: "Create account" }).click();
      await expect(page.getByText("Password must be at least 8 characters.")).toBeVisible();
      await expectNoViolations(page, "register, with an error showing");

      await page.goto("/login?deleted=1");
      await expect(page.getByTestId("deleted-notice")).toBeVisible();
      await expectNoViolations(page, "login after deleting an account");

      await page.goto("/about");
      await expect(page.getByTestId("stat-active_postings")).toHaveText("4,769");
      await expectNoViolations(page, "about");

      await page.goto("/privacy");
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expectNoViolations(page, "privacy");
    });

    test("profile, its delete dialog, and the building screen", async ({ page }) => {
      await signInDemo(page);
      await page.goto("/onboarding");
      await expect(page.getByTestId("ranked-interest").first()).toBeVisible();
      await expectNoViolations(page, "profile");

      // with every kind of inline message showing
      await page.getByLabel("Major").fill("M".repeat(121));
      await page.getByRole("button", { name: "Remove Security" }).click();
      await page.getByRole("button", { name: "Remove Software Engineering" }).click();
      await page.getByRole("button", { name: "Remove AI / ML / Data Science" }).click();
      await page.getByRole("textbox", { name: "Preferred locations" }).fill("x".repeat(101));
      await expectNoViolations(page, "profile, with validation messages");

      await page.getByTestId("open-delete").click();
      await expect(page.getByTestId("confirm-delete")).toBeVisible();
      await expectNoViolations(page, "delete dialog");
      await page.getByRole("button", { name: "Keep my account" }).click();

      await page.evaluate(() => localStorage.setItem("step1.mock.stuck", "1"));
      await page.goto("/onboarding/building?retry=1");
      await expect(page.getByTestId("building-step")).toHaveText("Scanning 4,139 open internships");
      await expectNoViolations(page, "building");
    });

    test("dashboard, its filters, its empty state and its warnings", async ({ page }, info) => {
      await signInDemo(page);
      await expect(page.getByTestId("freshness")).toBeVisible();
      await expectNoViolations(page, "dashboard");

      if (info.project.name === "mobile") {
        await page.getByTestId("open-filters").click();
        await expect(page.getByRole("checkbox", { name: "Security" })).toBeVisible();
        await page.getByRole("checkbox", { name: "Security" }).check();
        await page.getByRole("switch", { name: "Remote only" }).click();
        await expectNoViolations(page, "filter sheet");
        await page.getByTestId("close-filters").click();
      } else {
        await page.getByRole("checkbox", { name: "Security" }).check();
        await page.getByRole("switch", { name: "Remote only" }).click();
        await expect(page.getByTestId("posting-card")).toHaveCount(1);
        await expectNoViolations(page, "dashboard with filters on");
      }

      await page.goto("/?roles=security&location=Seattle&sort=score");
      await expect(page.getByTestId("relaxations")).toBeVisible();
      await expectNoViolations(page, "dashboard, empty state");

      await page.evaluate(() => localStorage.setItem("step1.mock.ingest", "failed"));
      await page.goto("/");
      await expect(page.getByTestId("freshness")).toHaveAttribute("data-tone", "warn");
      await expect(page.getByTestId("posting-card").first()).toBeVisible();
      await expectNoViolations(page, "dashboard, freshness warning");

      await page.evaluate(() => {
        localStorage.removeItem("step1.mock.ingest");
        localStorage.setItem("step1.mock.fail", "GET /feed");
      });
      await page.reload();
      await expect(page.locator('[role="alert"]:not(#__next-route-announcer__)').first()).toBeVisible();
      await expectNoViolations(page, "dashboard, error showing");

      await page.reload();
      await page.getByTestId("posting-card").first().getByTestId("apply-button").click();
      await expect(page.getByTestId("confirm-applied")).toBeVisible();
      await expectNoViolations(page, "I applied dialog");
    });

    test("saved, applications, timeline and its dialog", async ({ page }) => {
      await signInDemo(page);
      await page.goto("/saved");
      await expect(page.getByTestId("posting-card").first()).toBeVisible();
      await expectNoViolations(page, "saved");

      await page.goto("/applications");
      await expect(page.getByTestId("application-row").first()).toBeVisible();
      await expectNoViolations(page, "applications");

      await page.goto("/applications/12");
      await expect(page.getByTestId("timeline")).toBeVisible();
      await expectNoViolations(page, "timeline");

      await page.getByTestId("transition-button").first().click();
      await expect(page.getByTestId("save-event")).toBeVisible();
      await page.getByPlaceholder("Who you spoke to").fill("n".repeat(2001));
      await expectNoViolations(page, "event dialog, with a message showing");
      await page.getByRole("button", { name: "Cancel" }).click();

      for (const id of [9, 7]) {
        await page.goto(`/applications/${id}`);
        await expect(page.getByTestId("timeline")).toBeVisible();
        await expectNoViolations(page, id === 9 ? "timeline, ghosted" : "timeline, rejected");
      }

      await page.goto("/applications/99999");
      await expect(page.locator('[role="alert"]:not(#__next-route-announcer__)')).toBeVisible();
      await expectNoViolations(page, "timeline, not found");
    });
  });
}
