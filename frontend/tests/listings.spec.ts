// Internships and new grad roles: the Looking for setting, the kind filter,
// the New grad tag, and credit for every list.
import { expect, test, type Page } from "@playwright/test";
import { SOURCES } from "../src/lib/site";
import { signInDemo } from "./helpers";

const lastProfilePut = (page: Page) =>
  page.evaluate(() => {
    const w = window as unknown as { __step1Requests?: string[]; __step1Bodies?: Record<string, unknown>[] };
    const i = (w.__step1Requests ?? []).lastIndexOf("PUT /profile");
    return i === -1 ? null : (w.__step1Bodies ?? [])[i];
  });

async function lookFor(page: Page, kinds: ("Internships" | "New grad roles")[]) {
  await page.goto("/onboarding");
  const group = page.getByTestId("looking-for");
  await expect(group.getByRole("button", { name: "Internships" })).toBeVisible();
  for (const name of ["Internships", "New grad roles"] as const) {
    const button = group.getByRole("button", { name });
    const on = (await button.getAttribute("aria-pressed")) === "true";
    if (on !== kinds.includes(name)) await button.click();
  }
  await page.getByTestId("submit-profile").click();
  await expect(page).toHaveURL(/\/$/, { timeout: 15_000 });
}

test("Looking for: internships by default, at least one, and sent with the profile", async ({ page }) => {
  await signInDemo(page);
  await page.goto("/onboarding");
  const group = page.getByTestId("looking-for");
  await expect(group.getByRole("button", { name: "Internships" })).toHaveAttribute("aria-pressed", "true");
  await expect(group.getByRole("button", { name: "New grad roles" })).toHaveAttribute("aria-pressed", "false");

  await group.getByRole("button", { name: "Internships" }).click();
  await expect(page.getByText("Choose internships, new grad roles, or both.")).toBeVisible();
  await expect(page.getByTestId("submit-profile")).toBeDisabled();

  await group.getByRole("button", { name: "New grad roles" }).click();
  await expect(page.getByTestId("submit-profile")).toBeEnabled();
  await page.getByTestId("submit-profile").click();
  await expect(page).toHaveURL(/\/onboarding\/building/);
  expect((await lastProfilePut(page))?.looking_for).toEqual(["new_grad"]);
  await expect(page).toHaveURL(/\/$/, { timeout: 15_000 });

  // only new grad roles now
  const cards = page.getByTestId("posting-card");
  await expect(cards).toHaveCount(6);
  await expect(page.getByTestId("new-grad-tag")).toHaveCount(6);

  // and the setting comes back as saved
  await page.goto("/onboarding");
  await expect(group.getByRole("button", { name: "New grad roles" })).toHaveAttribute("aria-pressed", "true");
  await expect(group.getByRole("button", { name: "Internships" })).toHaveAttribute("aria-pressed", "false");
});

test("the kind filter lives in the URL, survives a reload, and the empty state names it", async ({ page }) => {
  await signInDemo(page);
  await lookFor(page, ["Internships", "New grad roles"]);
  const cards = page.getByTestId("posting-card");
  await expect(page.getByTestId("feed-total")).toHaveText("58 postings, newest first");

  await page.getByLabel("Kind of role").selectOption("new_grad");
  await expect(page).toHaveURL(/kind=new_grad/);
  await expect(cards).toHaveCount(6);
  for (const card of await cards.all()) await expect(card.getByTestId("new-grad-tag")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Kind of role")).toHaveValue("new_grad");
  await expect(cards).toHaveCount(6);

  await page.getByLabel("Kind of role").selectOption("internship");
  await expect(page).toHaveURL(/kind=internship/);
  await expect(page.getByTestId("feed-total")).toHaveText("52 postings match your filters, newest first");
  await expect(page.getByTestId("new-grad-tag")).toHaveCount(0);

  await page.getByLabel("Kind of role").selectOption("");
  await expect(page).not.toHaveURL(/kind=/);

  // no new grad Quantitative Finance roles: the filter is named and can be dropped
  await page.goto("/?roles=quant&kind=new_grad");
  await expect(page.getByTestId("empty-state")).toContainText("No Quantitative Finance new grad postings.");
  await page.getByTestId("relax-kind").click();
  await expect(page).toHaveURL(/\/\?roles=quant$/);
  await expect(cards).toHaveCount(4);
});

test("cards say which list a posting came from, including lists the app doesn't know yet", async ({ page }) => {
  await signInDemo(page);
  await page.goto("/?roles=product_management");
  const sources = page.getByTestId("posting-source");
  await expect(sources.first()).toBeVisible();
  const text = await sources.allInnerTexts();
  expect(text).toContain("via Jobright");
  expect(text).toContain("via A list we have not heard of");
});

test("every list is credited by name, with a link, in the footer, on About and on Privacy", async ({ page }) => {
  for (const path of ["/about", "/privacy"]) {
    await page.goto(path);
    for (const src of SOURCES) {
      await expect(page.getByRole("contentinfo").getByRole("link", { name: src.name })).toHaveAttribute("href", src.url);
      await expect(page.getByRole("main").getByRole("link", { name: src.name })).toHaveAttribute("href", src.url);
    }
  }
  expect(SOURCES.length).toBe(8);
});
