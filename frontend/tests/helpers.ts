import { expect, type Page } from "@playwright/test";

export const PASSWORD = "correct-horse-9";

/** The seeded user: already onboarded, lands on the dashboard. */
export const DEMO_EMAIL = "demo@umd.edu";

export function freshEmail(tag = "t"): string {
  return `${tag}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@umd.edu`;
}

export async function signIn(page: Page, email: string, mode: "login" | "register" = "login") {
  await page.goto("/login");
  if (mode === "register") await page.getByRole("tab", { name: "Register" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: mode === "login" ? "Sign in" : "Create account" }).click();
}

/** The app's error banners (Next's own route announcer is also role=alert). */
export function errorNote(page: Page) {
  return page.locator('[role="alert"]:not(#__next-route-announcer__)');
}

export async function signInDemo(page: Page) {
  await signIn(page, DEMO_EMAIL);
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("posting-card").first()).toBeVisible();
}

/** Fails if the page can scroll sideways or any visible element pokes past
 *  the right edge of the viewport. */
export async function expectNoHorizontalScroll(page: Page) {
  const result = await page.evaluate(() => {
    const vw = document.documentElement.clientWidth;
    const offenders: string[] = [];
    for (const el of Array.from(document.body.querySelectorAll<HTMLElement>("*"))) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none") continue;
      if (el.closest(".sr-only")) continue;
      // Content an ancestor clips (ellipsis, scroll areas) can't widen the page.
      let clipped = false;
      for (let a = el.parentElement; a && a !== document.body; a = a.parentElement) {
        if (getComputedStyle(a).overflowX !== "visible") {
          const ar = a.getBoundingClientRect();
          if (ar.right <= vw + 1 && ar.left >= -1) clipped = true;
          break;
        }
      }
      if (clipped) continue;
      if (r.right > vw + 1 || r.left < -1) {
        offenders.push(`${el.tagName.toLowerCase()}.${String(el.className).slice(0, 60)} [${Math.round(r.left)}..${Math.round(r.right)}]`);
      }
    }
    return {
      vw,
      scrollWidth: document.documentElement.scrollWidth,
      bodyScrollWidth: document.body.scrollWidth,
      offenders: offenders.slice(0, 5),
    };
  });
  expect(result.offenders, `elements wider than the ${result.vw}px viewport`).toEqual([]);
  expect(result.scrollWidth).toBeLessThanOrEqual(result.vw);
  expect(result.bodyScrollWidth).toBeLessThanOrEqual(result.vw);
}

/** A tiny but valid-looking PDF payload for the upload input. */
export function pdfFile(name = "resume.pdf") {
  return {
    name,
    mimeType: "application/pdf",
    buffer: Buffer.from("%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"),
  };
}
