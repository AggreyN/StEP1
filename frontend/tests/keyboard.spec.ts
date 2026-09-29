// Everything here is done with the keyboard alone: no click(), no fill().
// Focus is moved with Tab and Shift+Tab, controls are worked with Enter,
// Space and the arrow keys, and text is typed.
import { expect, test, type Locator, type Page } from "@playwright/test";
import { PASSWORD, freshEmail } from "./helpers";

const focused = (l: Locator) => l.evaluate((el) => el === document.activeElement).catch(() => false);

/** Press Tab (or Shift+Tab) until `target` has focus. Fails if it can't be reached. */
async function tabTo(page: Page, target: Locator, opts: { back?: boolean; max?: number } = {}) {
  const { back = false, max = 150 } = opts;
  for (let i = 0; i < max; i++) {
    if (await focused(target)) return;
    await page.keyboard.press(back ? "Shift+Tab" : "Tab");
  }
  expect(await focused(target), `could not reach ${target} with the ${back ? "Shift+Tab" : "Tab"} key`).toBe(true);
}

/** The focused element must show a focus ring that is really visible. */
async function expectFocusRing(page: Page) {
  const ring = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement;
    const label = el.matches("input.sr-only") ? (el.nextElementSibling as HTMLElement) : el;
    const cs = getComputedStyle(label);
    return { style: cs.outlineStyle, width: parseFloat(cs.outlineWidth), color: cs.outlineColor, tag: el.tagName };
  });
  expect(ring.style, `focus ring on <${ring.tag}>`).not.toBe("none");
  expect(ring.width).toBeGreaterThanOrEqual(2);
  expect(ring.color).not.toBe("rgba(0, 0, 0, 0)");
}

async function signInByKeyboard(page: Page, email: string, register: boolean) {
  await page.goto("/login");
  if (register) {
    await tabTo(page, page.getByRole("tab", { name: "Sign in" }));
    await page.keyboard.press("ArrowRight");
    await expect(page.getByRole("tab", { name: "Register" })).toBeFocused();
    await expect(page.getByRole("tab", { name: "Register" })).toHaveAttribute("aria-selected", "true");
  }
  await tabTo(page, page.getByLabel("Email"));
  await expectFocusRing(page);
  await page.keyboard.type(email);
  await tabTo(page, page.getByLabel("Password"));
  await page.keyboard.type(PASSWORD);
  await page.keyboard.press("Enter"); // submits the form
}

test("rank interests with the keyboard alone", async ({ page }) => {
  await signInByKeyboard(page, freshEmail("kbd"), true);
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByLabel("Major")).toBeVisible();

  // pick four fields
  for (const name of ["+ Security", "+ Software Engineering", "+ Research", "+ Design & UX"]) {
    await tabTo(page, page.getByRole("button", { name }));
    await expectFocusRing(page);
    await page.keyboard.press("Enter");
  }
  const ranked = page.getByTestId("ranked-interest");
  await expect(ranked).toHaveText([/^1Security/, /^2Software Engineering/, /^3Research/, /^4Design & UX/]);

  // move Research (3) up twice, to the top
  const up = page.getByRole("button", { name: "Move Research up" });
  await tabTo(page, up, { back: true });
  await page.keyboard.press("Enter");
  await expect(ranked).toHaveText([/^1Security/, /^2Research/, /^3Software Engineering/, /^4Design & UX/]);
  await expect(up).toBeFocused(); // focus travelled with the item
  await expect(page.getByTestId("rank-announcement")).toHaveText("Research is now number 2 of 4.");
  await page.keyboard.press("Space");
  await expect(ranked).toHaveText([/^1Research/, /^2Security/, /^3Software Engineering/, /^4Design & UX/]);

  // at the top the button can't do anything more, but focus is not lost
  await expect(up).toBeFocused();
  await expect(up).toHaveAttribute("aria-disabled", "true");
  await page.keyboard.press("Enter");
  await expect(ranked.nth(0)).toContainText("Research");

  // move it down one, from the button next to it
  await page.keyboard.press("Tab");
  await expect(page.getByRole("button", { name: "Move Research down" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(ranked).toHaveText([/^1Security/, /^2Research/, /^3Software Engineering/, /^4Design & UX/]);

  // remove one
  await tabTo(page, page.getByRole("button", { name: "Remove Design & UX" }));
  await page.keyboard.press("Enter");
  await expect(ranked).toHaveCount(3);
  await expect(page.getByTestId("rank-announcement")).toHaveText("Design & UX removed.");

  // the rest of the form: major, a location, the upload button, submit
  await tabTo(page, page.getByLabel("Major"));
  await page.keyboard.type("Information Science");
  await tabTo(page, page.getByRole("button", { name: "Fall 2027" }));
  await page.keyboard.press("Space");
  await expect(page.getByRole("button", { name: "Fall 2027" })).toHaveAttribute("aria-pressed", "true");

  const locations = page.getByRole("textbox", { name: "Preferred locations" });
  await tabTo(page, locations);
  await page.keyboard.type("Washington, DC");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("list", { name: "Preferred locations" }).getByRole("listitem")).toHaveCount(1);
  await expect(locations).toBeFocused(); // ready for the next one

  await tabTo(page, page.locator("#resume-file"));
  await expectFocusRing(page); // the ring is drawn on the visible "Upload PDF" button

  await tabTo(page, page.getByTestId("submit-profile"));
  await expectFocusRing(page);
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/onboarding\/building/);
  await expect(page).toHaveURL(/\/$/, { timeout: 15_000 });

  // what was saved is what was ranked
  await page.goto("/onboarding");
  await expect(page.getByTestId("ranked-interest")).toHaveText([/^1Security/, /^2Research/, /^3Software Engineering/]);
});

test("save, apply and advance the timeline with the keyboard alone", async ({ page }) => {
  await signInByKeyboard(page, "demo@umd.edu", false);
  await expect(page).toHaveURL(/\/$/);
  const card = page.getByTestId("posting-card").filter({ has: page.getByTestId("apply-button") }).filter({
    has: page.getByRole("button", { name: "Save", exact: true }),
  }).first();
  await expect(card).toBeVisible();
  const id = await card.getAttribute("data-posting-id");
  const mine = page.locator(`[data-posting-id="${id}"]`);

  // the skip link is the first stop, and it skips the navigation
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeVisible();

  // sort is one stop, changed with the arrow keys
  await tabTo(page, page.getByRole("radio", { name: "Newest first" }));
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/sort=score/);
  await expect(page.getByRole("radio", { name: "Best match" })).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(page).not.toHaveURL(/sort=/);
  await expect(page.getByTestId("posting-card").first()).toBeVisible();

  // save
  const star = mine.getByTestId("save-toggle");
  await tabTo(page, star);
  await expectFocusRing(page);
  await expect(star).toHaveAccessibleName("Save");
  await page.keyboard.press("Enter");
  await expect(star).toHaveAttribute("aria-pressed", "true");
  await expect(star).toHaveAccessibleName("Unsave");
  await expect(star).toBeFocused(); // focus stayed put while it saved
  await expect(star).toBeEnabled();

  // apply: the dialog takes focus, keeps it, and gives it back on Escape
  const apply = mine.getByTestId("apply-button");
  await tabTo(page, apply);
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Track this application" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel("Date applied")).toBeFocused();
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    const inside = await page.evaluate(() => {
      const a = document.activeElement;
      // focus may pass through the browser's own UI, never the page behind
      return !a || a === document.body || !!a.closest("dialog");
    });
    expect(inside, "focus left the dialog").toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(apply).toBeFocused();

  await page.keyboard.press("Enter");
  await expect(dialog).toBeVisible();
  await tabTo(page, dialog.getByTestId("confirm-applied"));
  await page.keyboard.press("Enter");
  await expect(dialog).toBeHidden();
  const link = mine.getByTestId("application-link");
  await expect(link).toBeFocused(); // the button it replaced is gone
  await page.keyboard.press("Enter");

  // timeline
  await expect(page).toHaveURL(/\/application\?id=\d+$/);
  await expect(page.getByTestId("timeline-event")).toHaveCount(1);
  const first = page.getByTestId("transition-button").first();
  const kind = await first.getAttribute("data-kind");
  await tabTo(page, first);
  await expectFocusRing(page);
  await page.keyboard.press("Enter");
  const eventDialog = page.getByRole("dialog");
  await expect(eventDialog).toBeVisible();
  await expect(eventDialog.getByRole("textbox", { name: /Note/ })).toBeFocused();
  await page.keyboard.type("Typed without a mouse");
  await tabTo(page, eventDialog.getByTestId("save-event"));
  await page.keyboard.press("Enter");
  await expect(eventDialog).toBeHidden();

  await expect(page.getByTestId("status-pill").first()).toHaveAttribute("data-status", kind!);
  await expect(page.getByTestId("timeline")).toContainText("Typed without a mouse");
  await expect(page.getByRole("heading", { name: "What happened next?" })).toBeFocused();
  await expect(page.getByTestId("timeline-announcement")).toContainText("Recorded. This application is now:");

  // and straight on to the next step from there
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("transition-button").first()).toBeFocused();

  // a note, then Escape out of a second dialog returns focus to its opener
  await tabTo(page, page.getByTestId("add-note"));
  await page.keyboard.press("Enter");
  await expect(eventDialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(eventDialog).toBeHidden();
  await expect(page.getByTestId("add-note")).toBeFocused();
});

test("the delete dialog traps focus and returns it", async ({ page }) => {
  await signInByKeyboard(page, "demo@umd.edu", false);
  await expect(page).toHaveURL(/\/$/);
  await page.goto("/onboarding");
  const open = page.getByTestId("open-delete");
  await expect(open).toBeVisible();
  await tabTo(page, open, { back: true });
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "Delete your account?" });
  await expect(dialog.getByLabel("Your password")).toBeFocused();
  await page.keyboard.type("anything");
  await page.keyboard.press("Enter"); // Enter in the field must not delete: the box isn't ticked
  await expect(dialog).toBeVisible();
  await expect(page).toHaveURL(/\/onboarding$/);
  await tabTo(page, dialog.getByRole("checkbox"));
  await page.keyboard.press("Space");
  await expect(dialog.getByRole("checkbox")).toBeChecked();
  await tabTo(page, dialog.getByRole("button", { name: "Keep my account" }));
  await page.keyboard.press("Enter");
  await expect(dialog).toBeHidden();
  await expect(open).toBeFocused();
});

test("on a phone the filter sheet works from the keyboard and gives focus back", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await signInByKeyboard(page, "demo@umd.edu", false);
  await expect(page).toHaveURL(/\/$/);
  const open = page.getByTestId("open-filters");
  await tabTo(page, open);
  await page.keyboard.press("Enter");
  const sheet = page.getByRole("dialog", { name: "Filters" });
  await expect(sheet).toBeVisible();
  await tabTo(page, sheet.getByRole("checkbox", { name: "Security" }));
  await page.keyboard.press("Space");
  await expect(page).toHaveURL(/roles=security/);
  await tabTo(page, sheet.getByRole("switch", { name: "Remote only" }));
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/remote=true/);
  await page.keyboard.press("Escape");
  await expect(sheet).toBeHidden();
  await expect(open).toBeFocused();
  await expect(page.getByTestId("posting-card")).toHaveCount(1);
});
