// 375px: every screen must be usable with no horizontal scroll.
import { expect, test } from "@playwright/test";
import { expectNoHorizontalScroll, freshEmail, signIn, signInDemo } from "./helpers";

test("login and onboarding fit at 375px", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expectNoHorizontalScroll(page);

  await page.goto("/no/such/page");
  await expect(page.getByRole("heading", { name: "Page not found" })).toBeVisible();
  await expectNoHorizontalScroll(page);
  await page.goto("/auth/callback");
  await expect(page.getByRole("heading", { name: "Nothing to finish here" })).toBeVisible();
  await expectNoHorizontalScroll(page);
  await page.goto("/login");

  await signIn(page, freshEmail("mobile"), "register");
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByLabel("Major")).toBeVisible();
  for (const name of ["+ Technical Program Management", "+ Solutions & Sales Engineering", "+ Data & Business Analytics"]) {
    await page.getByRole("button", { name }).click();
  }
  await page.getByRole("textbox", { name: "Preferred locations" }).fill("San Francisco Bay Area, California");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expectNoHorizontalScroll(page);

  await page.getByLabel("Major").fill("Information Science");
  await page.getByTestId("submit-profile").click();
  await expect(page).toHaveURL(/\/onboarding\/building/);
  await expectNoHorizontalScroll(page);
  await expect(page).toHaveURL(/\/$/, { timeout: 15_000 });
});

test("dashboard, filter sheet, saved and applications fit at 375px", async ({ page }) => {
  await signInDemo(page);

  // the sort control sits beside the Filters button and fits
  const sort = page.getByTestId("sort-control");
  await expect(sort).toBeVisible();
  const box = await sort.boundingBox();
  const filtersBox = await page.getByTestId("open-filters").boundingBox();
  expect(box!.x).toBeGreaterThanOrEqual(0);
  expect(box!.x + box!.width).toBeLessThanOrEqual(filtersBox!.x);
  expect(filtersBox!.x + filtersBox!.width).toBeLessThanOrEqual(375);
  expect(Math.abs(box!.y + box!.height / 2 - (filtersBox!.y + filtersBox!.height / 2))).toBeLessThan(4);
  await page.getByRole("radio", { name: "Best match" }).click();
  await expect(page).toHaveURL(/sort=score/);
  await expect(page.getByTestId("feed-total")).toHaveText("52 postings, best match first");
  await expectNoHorizontalScroll(page);
  await page.getByRole("radio", { name: "Newest first" }).click();
  await expect(page).not.toHaveURL(/sort=/);

  await page.getByTestId("load-more").click();
  await expect(page.getByTestId("posting-card")).toHaveCount(40);
  await expectNoHorizontalScroll(page);

  // filters live in a sheet on mobile
  await expect(page.getByRole("checkbox", { name: "Security" })).toBeHidden();
  await page.getByTestId("open-filters").click();
  await page.getByRole("checkbox", { name: "Security" }).check();
  await expect(page).toHaveURL(/roles=security/);
  await expectNoHorizontalScroll(page);
  await page.getByTestId("close-filters").click();
  await expect(page.getByTestId("posting-card")).toHaveCount(4);
  await expect(page.getByTestId("open-filters")).toContainText("1");

  await page.goto("/?roles=program_management,solutions_architecture&location=Annapolis+Junction&min_score=90");
  await expect(page.getByTestId("empty-state")).toBeVisible();
  await expect(page.getByTestId("relaxations").or(page.getByTestId("no-single-filter"))).toBeVisible();
  await expectNoHorizontalScroll(page);

  await page.goto("/saved");
  await expect(page.getByTestId("posting-card").first()).toBeVisible();
  await expectNoHorizontalScroll(page);

  await page.goto("/applications");
  await expect(page.getByTestId("application-row").first()).toBeVisible();
  await expectNoHorizontalScroll(page);

  await page.goto("/application?id=12");
  await expect(page.getByTestId("timeline")).toBeVisible();
  await expectNoHorizontalScroll(page);
  await page.getByTestId("transition-button").first().click();
  await expect(page.getByTestId("save-event")).toBeVisible();
  await expectNoHorizontalScroll(page);
});
