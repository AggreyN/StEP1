// Local sign-in, in both settings of NEXT_PUBLIC_REGISTRATION, on the
// exported site.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { PASSWORD, freshEmail } from "../tests/helpers";
import { SITES } from "./support/sites.mjs";

const at = (site: { port: number }, path: string) => `http://localhost:${site.port}${path}`;

test("open (the default): the sign-in page offers to register", async ({ page }) => {
  await page.goto(at(SITES.local, "/login"));
  await expect(page.getByRole("tab", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Register" })).toBeVisible();
  await expect(page.getByTestId("invite-only")).toHaveCount(0);
  await expect(page.getByLabel("Password")).toBeVisible();
});

test("closed: no way to register, and only existing accounts can sign in", async ({ page }) => {
  await page.goto(at(SITES.closed, "/login"));
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await expect(page.getByRole("tab")).toHaveCount(0);
  await expect(page.getByRole("tablist")).toHaveCount(0);
  await expect(page.getByText("Register")).toHaveCount(0);
  await expect(page.getByText("Create account")).toHaveCount(0);
  await expect(page.getByLabel(/^Name/)).toHaveCount(0);
  await expect(page.getByTestId("invite-only")).toContainText("Accounts are by invitation.");
  await expect(page.getByTestId("invite-only").getByRole("link", { name: "Ask for one" })).toHaveAttribute("href", "/about");

  // someone without an account
  await page.getByLabel("Email").fill(freshEmail("closed"));
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator('[role="alert"]:not(#__next-route-announcer__)')).toHaveText("Incorrect email or password.");
  await expect(page).toHaveURL(/\/login$/);

  // someone with one
  await page.getByLabel("Email").fill("demo@umd.edu");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(new RegExp(`^${at(SITES.closed, "/")}$`));
  await expect(page.getByTestId("posting-card").first()).toBeVisible();
});

for (const scheme of ["light", "dark"] as const) {
  test(`closed: the sign-in page is accessible (${scheme})`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto(at(SITES.closed, "/login"));
    await expect(page.getByTestId("invite-only")).toBeVisible();
    await page.evaluate(() => document.fonts.ready);
    const { violations } = await new AxeBuilder({ page }).analyze();
    expect(violations.map((v) => ({ rule: v.id, nodes: v.nodes.map((n) => n.target.join(" ")) }))).toEqual([]);
  });
}

test("local mode: the Cognito callback address explains itself", async ({ page }) => {
  await page.goto(at(SITES.local, "/auth/callback?code=abc&state=def"));
  await expect(page.getByRole("heading", { name: "Nothing to finish here" })).toBeVisible();
  await expect(page.getByTestId("callback-unused")).toBeVisible();
  await page.getByRole("link", { name: "Go to sign in" }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(await page.evaluate(() => localStorage.getItem("step1.token"))).toBeNull();
});
