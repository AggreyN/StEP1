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

test("ghosted is quiet and muted, not styled like a rejection", async ({ page }) => {
  await page.goto("/applications/9");
  const ghosted = page.locator('[data-testid="timeline-event"][data-kind="ghosted"]');
  await expect(ghosted).toContainText("Ghosted");
  await expect(ghosted).toContainText("Logged automatically");

  // Resolve the palette's own tokens, so this holds whatever the palette is.
  const token = (name: string) =>
    page.evaluate((n) => {
      const probe = document.createElement("span");
      probe.style.color = `var(--${n})`;
      document.body.append(probe);
      const c = getComputedStyle(probe).color;
      probe.remove();
      return c;
    }, name);
  const pill = (status: string) => page.locator(`[data-testid="status-pill"][data-status="${status}"]`).first();
  const look = (status: string) =>
    pill(status).evaluate((el) => {
      const cs = getComputedStyle(el);
      return { color: cs.color, background: cs.backgroundColor, border: cs.borderTopStyle };
    });

  const ghost = await look("ghosted");
  expect(ghost.color).toBe(await token("faint")); // the quietest text colour
  expect(ghost.color).not.toBe(await token("danger"));
  expect(ghost.background).toBe("rgba(0, 0, 0, 0)"); // no fill
  expect(ghost.border).toBe("dashed");

  await page.goto("/applications/7");
  const rejected = await look("rejected");
  expect(rejected.color).toBe(await token("danger"));
  expect(rejected.background).toBe(await page.evaluate(() => {
    const probe = document.createElement("span");
    probe.style.backgroundColor = "var(--danger-soft)";
    document.body.append(probe);
    const c = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return c;
  }));
  expect(rejected.color).not.toBe(ghost.color);
});

test("an unknown application shows the API's message", async ({ page }) => {
  await page.goto("/applications/99999");
  await expect(errorNote(page)).toContainText("Application not found");
});
