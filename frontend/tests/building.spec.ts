import { expect, test } from "@playwright/test";
import status from "../src/lib/mock/status.json";
import { signInDemo } from "./helpers";

test("building: routes straight through when the first poll is already ready", async ({ page }) => {
  await signInDemo(page);
  await page.evaluate(() => localStorage.setItem("step1.mock.instant", "1"));
  const started = Date.now();
  await page.goto("/onboarding/building?retry=1");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("posting-card").first()).toBeVisible();
  // one poll (300 ms mock latency) plus navigation — no artificial wait
  expect(Date.now() - started).toBeLessThan(5_000);
});

test("building: polls, shows each real step, then routes to the dashboard", async ({ page }) => {
  await signInDemo(page);
  await page.goto("/onboarding");
  await page.getByTestId("submit-profile").click();
  await expect(page).toHaveURL(/\/onboarding\/building\?retry=1/);

  const seen = new Set<string>();
  const step = page.getByTestId("building-step");
  while (page.url().includes("/building")) {
    const text = await step.textContent({ timeout: 1_000 }).catch(() => null);
    if (text && text !== "Connecting…") seen.add(text);
    await page.waitForTimeout(100);
  }
  const building = status.sequence.filter((s) => s.state === "building").map((s) => s.step);
  expect([...seen]).toEqual(expect.arrayContaining(building));
  await expect(page).toHaveURL(/\/$/);
});
