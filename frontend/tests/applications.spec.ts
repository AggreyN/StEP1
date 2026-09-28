import { expect, test } from "@playwright/test";
import { errorNote, signInDemo } from "./helpers";

test.beforeEach(async ({ page }) => {
  await signInDemo(page);
});

test("applications are grouped by status with a count per group", async ({ page }) => {
  await page.getByRole("link", { name: "Applications" }).click();
  const groups = page.getByTestId("status-group");
  await expect(groups).toHaveCount(4);
  for (const status of ["applied", "interview_scheduled", "ghosted", "rejected"]) {
    const g = page.locator(`[data-testid="status-group"][data-status="${status}"]`);
    await expect(g.getByTestId("group-count")).toHaveText("1");
    await expect(g.getByTestId("application-row")).toHaveCount(1);
  }
});

test("ghosted is quiet and grey, not styled like a rejection", async ({ page }) => {
  await page.goto("/applications/9");
  const ghosted = page.locator('[data-testid="timeline-event"][data-kind="ghosted"]');
  await expect(ghosted).toContainText("Ghosted");
  await expect(ghosted).toContainText("Logged automatically");

  const pillColor = (status: string) =>
    page.locator(`[data-testid="status-pill"][data-status="${status}"]`).first().evaluate((el) => getComputedStyle(el).color);
  const ghostColor = await pillColor("ghosted");
  await page.goto("/applications/7");
  const rejectedColor = await pillColor("rejected");
  expect(ghostColor).not.toBe(rejectedColor);

  // grey means the channels are (near) equal; the rejection colour is red-dominant
  const rgb = (c: string) => (c.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
  const [gr, gg, gb] = rgb(ghostColor);
  expect(Math.max(gr, gg, gb) - Math.min(gr, gg, gb)).toBeLessThan(30);
  const [rr, rg, rb] = rgb(rejectedColor);
  expect(rr - Math.max(rg, rb)).toBeGreaterThan(60);
});

test("an unknown application shows the API's message", async ({ page }) => {
  await page.goto("/applications/99999");
  await expect(errorNote(page)).toContainText("Application not found");
});
