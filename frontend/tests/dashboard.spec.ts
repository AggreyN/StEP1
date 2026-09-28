import { expect, test } from "@playwright/test";
import { errorNote, signInDemo } from "./helpers";

test.beforeEach(async ({ page }) => {
  await signInDemo(page);
});

test("filters write to the URL and a reload restores them", async ({ page }) => {
  await page.getByRole("checkbox", { name: "Security" }).check();
  await expect(page).toHaveURL(/roles=security/);
  await page.getByLabel("Minimum score").selectOption("80");
  await expect(page).toHaveURL(/min_score=80/);
  await page.getByLabel("Term").selectOption("Summer 2027");
  await expect(page).toHaveURL(/term=Summer\+2027/);
  await page.getByRole("switch", { name: "Remote only" }).click();
  await expect(page).toHaveURL(/remote=true/);

  const cards = page.getByTestId("posting-card");
  await expect(page.getByTestId("feed-total")).toHaveText("1 posting matches your filters");
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText("CrowdStrike");
  const url = page.url();

  await page.reload();
  expect(page.url()).toBe(url);
  await expect(page.getByRole("checkbox", { name: "Security" })).toBeChecked();
  await expect(page.getByLabel("Minimum score")).toHaveValue("80");
  await expect(page.getByLabel("Term")).toHaveValue("Summer 2027");
  await expect(page.getByRole("switch", { name: "Remote only" })).toHaveAttribute("aria-checked", "true");
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText("CrowdStrike");
});

test("typed location filter lands in the URL and survives a reload", async ({ page }) => {
  await page.getByLabel("Location").fill("New York");
  await expect(page).toHaveURL(/location=New\+York/);
  await expect(page.getByTestId("posting-card").first()).toContainText("New York");
  await page.reload();
  await expect(page.getByLabel("Location")).toHaveValue("New York");
  await expect(page.getByTestId("posting-card").first()).toContainText("New York");
});

test("results are sorted by score and load-more pages through has_more", async ({ page }) => {
  const cards = page.getByTestId("posting-card");
  await expect(cards).toHaveCount(20);
  await page.getByTestId("load-more").click();
  await expect(cards).toHaveCount(40);
  await page.getByTestId("load-more").click();
  await expect(cards).toHaveCount(52);
  await expect(page.getByTestId("load-more")).toHaveCount(0);
  const scores = await cards.evaluateAll((els) =>
    els.map((e) => Number(e.querySelector("[aria-label^='Match score']")?.textContent))
  );
  expect(scores).toEqual([...scores].sort((a, b) => b - a));
  expect(Math.max(...scores)).toBeGreaterThanOrEqual(90);
  expect(Math.min(...scores)).toBeLessThanOrEqual(30);
});

test("empty state names the responsible filter and removing it brings results back", async ({ page }) => {
  await page.goto("/?roles=security&location=Seattle");
  const empty = page.getByTestId("empty-state");
  await expect(empty).toContainText("No Security postings in Seattle.");
  await expect(empty).toContainText("4 Security postings elsewhere");
  // dropping the role filter would also help, and says so
  await expect(empty).toContainText("postings in Seattle in other fields");

  await page.getByTestId("relax-location").click();
  await expect(page).toHaveURL(/\/\?roles=security$/);
  await expect(page.getByTestId("posting-card")).toHaveCount(4);
  await expect(page.getByLabel("Location")).toHaveValue("");
});

// Every combination below returns zero results in the fixture data.
const EMPTY_CASES: { name: string; query: string; headline: string; responsible: string[] }[] = [
  { name: "term alone", query: "term=Winter+2027", headline: "No postings for Winter 2027.", responsible: ["term"] },
  { name: "score too high for a thin role", query: "roles=design_ux&min_score=80", headline: "No Design & UX postings scoring 80+.", responsible: ["min_score"] },
  { name: "remote-only on an on-site field", query: "roles=quant&remote=true", headline: "No remote Quantitative Finance postings.", responsible: ["remote"] },
  { name: "location nobody posts in", query: "location=Anchorage", headline: "No postings in Anchorage.", responsible: ["location"] },
  { name: "two roles, one term", query: "roles=program_management,it_support&term=Fall+2027", headline: "No Technical Program Management or IT & Systems postings for Fall 2027.", responsible: ["term"] },
  { name: "role and location each to blame", query: "roles=hardware&location=Seattle&remote=true", headline: "No remote Hardware & Embedded postings in Seattle.", responsible: ["roles"] },
];

for (const c of EMPTY_CASES) {
  test(`empty state: ${c.name}`, async ({ page }) => {
    await page.goto(`/?${c.query}`);
    const empty = page.getByTestId("empty-state");
    await expect(empty).toContainText(c.headline);
    for (const key of c.responsible) {
      await expect(page.getByTestId(`relax-${key}`)).toBeVisible();
    }
    // taking the offered way out always produces results
    await page.getByTestId(`relax-${c.responsible[0]}`).click();
    await expect(page.getByTestId("posting-card").first()).toBeVisible();
    await expect(page.getByTestId("empty-state")).toHaveCount(0);
  });
}

test("empty state: when no single filter is to blame it says so and offers a reset", async ({ page }) => {
  await page.goto("/?roles=design_ux&location=Anchorage&term=Winter+2027");
  const empty = page.getByTestId("empty-state");
  await expect(empty).toContainText("No Design & UX postings in Anchorage for Winter 2027.");
  await expect(page.getByTestId("no-single-filter")).toContainText("role filter, location filter, term filter");
  await page.getByRole("button", { name: "Clear all filters" }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByTestId("posting-card")).toHaveCount(20);
});

test("save is optimistic and rolls back when the API fails", async ({ page }) => {
  const card = page
    .getByTestId("posting-card")
    .filter({ has: page.getByRole("button", { name: "Save", exact: true }) })
    .first();
  const id = await card.getAttribute("data-posting-id");
  const toggle = page.locator(`[data-posting-id="${id}"]`).getByTestId("save-toggle");

  await page.evaluate(() => localStorage.setItem("step1.mock.fail", "POST /saved"));
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "true"); // flips immediately
  await expect(errorNote(page)).toContainText("The server had a problem");
  await expect(toggle).toHaveAttribute("aria-pressed", "false"); // rolled back

  await toggle.click(); // and works once the API recovers
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(toggle).toBeEnabled(); // request finished
  await page.reload();
  await expect(page.locator(`[data-posting-id="${id}"]`).getByTestId("save-toggle")).toHaveAttribute("aria-pressed", "true");
});

test("a failed 'I applied' shows the API's error and can be retried", async ({ page }) => {
  const card = page.getByTestId("posting-card").filter({ has: page.getByTestId("apply-button") }).first();
  const id = await card.getAttribute("data-posting-id");
  await card.getByTestId("apply-button").click();
  await page.evaluate(() => localStorage.setItem("step1.mock.fail", "POST /applications"));
  await page.getByTestId("confirm-applied").click();
  await expect(errorNote(page)).toContainText("The server had a problem");
  await page.getByTestId("confirm-applied").click();
  await expect(page.locator(`[data-posting-id="${id}"]`).getByTestId("application-link")).toBeVisible();
});
