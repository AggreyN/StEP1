import { expect, test, type Page } from "@playwright/test";
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
  await expect(page.getByTestId("feed-total")).toHaveText("1 posting matches your filters, newest first");
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

type Row = { date: string; score: number };

async function rows(page: Page): Promise<Row[]> {
  return page.getByTestId("posting-card").evaluateAll((els) =>
    els.map((e) => ({
      date: e.getAttribute("data-date-posted") ?? "",
      score: Number(e.getAttribute("data-score")),
    }))
  );
}

/** Newest first, undated last; ties broken by higher score. */
function expectNewestFirst(list: Row[]) {
  for (let i = 1; i < list.length; i++) {
    const prev = list[i - 1];
    const cur = list[i];
    const where = `row ${i}: ${JSON.stringify(prev)} then ${JSON.stringify(cur)}`;
    if (!prev.date) expect(cur.date, `a dated posting after an undated one — ${where}`).toBe("");
    if (prev.date && cur.date) expect(prev.date >= cur.date, where).toBe(true);
    if (prev.date === cur.date) expect(prev.score, where).toBeGreaterThanOrEqual(cur.score);
  }
}

/** Highest score first; ties broken by newer date, undated last. */
function expectBestMatchFirst(list: Row[]) {
  for (let i = 1; i < list.length; i++) {
    const prev = list[i - 1];
    const cur = list[i];
    const where = `row ${i}: ${JSON.stringify(prev)} then ${JSON.stringify(cur)}`;
    expect(prev.score, where).toBeGreaterThanOrEqual(cur.score);
    if (prev.score === cur.score) expect(prev.date >= cur.date, where).toBe(true);
  }
}

test("default order is newest first, undated postings last, and load-more keeps it", async ({ page }) => {
  await expect(page).toHaveURL(/\/$/); // no sort param for the default
  await expect(page.getByRole("radio", { name: "Newest first" })).toBeChecked();
  await expect(page.getByTestId("feed-total")).toHaveText("52 postings, newest first");

  const cards = page.getByTestId("posting-card");
  await expect(cards).toHaveCount(20);
  expectNewestFirst(await rows(page));

  await page.getByTestId("load-more").click();
  await expect(cards).toHaveCount(40);
  expectNewestFirst(await rows(page));
  await page.getByTestId("load-more").click();
  await expect(cards).toHaveCount(52);
  await expect(page.getByTestId("load-more")).toHaveCount(0);

  const all = await rows(page);
  expectNewestFirst(all);
  // the fixture has two undated postings; they are the last two rows
  expect(all.filter((r) => !r.date)).toHaveLength(2);
  expect(all.slice(-2).every((r) => !r.date)).toBe(true);
  // and this is not just score order in disguise
  expect(all.map((r) => r.score)).not.toEqual([...all.map((r) => r.score)].sort((x, y) => y - x));
  // every card still carries its score badge and reasons
  await expect(cards.first().getByLabel(/^Match score \d+ out of 100$/)).toBeVisible();
  await expect(cards.first().getByRole("list", { name: "Why this matches" })).toBeVisible();
});

test("Best match sorts by score, lives in the URL, survives reload, and switching back removes it", async ({ page }) => {
  const cards = page.getByTestId("posting-card");
  await expect(cards).toHaveCount(20);
  await page.getByTestId("load-more").click();
  await expect(cards).toHaveCount(40);

  await page.getByRole("radio", { name: "Best match" }).click();
  await expect(page).toHaveURL(/\/\?sort=score$/);
  await expect(page.getByTestId("feed-total")).toHaveText("52 postings, best match first");
  await expect(cards).toHaveCount(20); // back to page 1
  let list = await rows(page);
  expectBestMatchFirst(list);
  expect(list[0].score).toBeGreaterThanOrEqual(90);

  await page.getByTestId("load-more").click();
  await expect(cards).toHaveCount(40);
  await page.getByTestId("load-more").click();
  await expect(cards).toHaveCount(52);
  list = await rows(page);
  expectBestMatchFirst(list);
  expect(list[list.length - 1].score).toBeLessThanOrEqual(30);

  await page.reload();
  await expect(page).toHaveURL(/\/\?sort=score$/);
  await expect(page.getByRole("radio", { name: "Best match" })).toBeChecked();
  await expect(cards).toHaveCount(20);
  expectBestMatchFirst(await rows(page));

  await page.getByRole("radio", { name: "Newest first" }).click();
  await expect(page).toHaveURL(/\/$/);
  expect(page.url()).not.toContain("sort");
  await expect(page.getByTestId("feed-total")).toHaveText("52 postings, newest first");
  await expect(cards).toHaveCount(20);
  expectNewestFirst(await rows(page));
});

test("sort and filters combine in the URL, and clearing filters keeps the sort", async ({ page }) => {
  await page.getByRole("radio", { name: "Best match" }).click();
  await page.getByRole("checkbox", { name: "Software Engineering" }).check();
  await expect(page).toHaveURL(/\/\?roles=software&sort=score$/);
  await expect(page.getByTestId("feed-total")).toHaveText("19 postings match your filters, best match first");
  const cards = page.getByTestId("posting-card");
  await expect(cards).toHaveCount(19);
  expectBestMatchFirst(await rows(page));

  await page.reload();
  await expect(page.getByRole("checkbox", { name: "Software Engineering" })).toBeChecked();
  await expect(page.getByRole("radio", { name: "Best match" })).toBeChecked();
  await expect(cards).toHaveCount(19);

  await page.getByRole("button", { name: "Clear all" }).click();
  await expect(page).toHaveURL(/\/\?sort=score$/);
  await expect(page.getByTestId("feed-total")).toHaveText("52 postings, best match first");
});

test("every feed request names its sort, including empty-state probes", async ({ page }) => {
  const feedRequests = () =>
    page.evaluate(() =>
      ((window as unknown as { __step1Requests?: string[] }).__step1Requests ?? []).filter((r) =>
        r.startsWith("GET /feed?")
      )
    );
  await page.getByRole("radio", { name: "Best match" }).click();
  await expect(page.getByTestId("feed-total")).toContainText("best match first");
  await page.getByTestId("load-more").click();
  await expect(page.getByTestId("posting-card")).toHaveCount(40);
  await page.getByRole("radio", { name: "Newest first" }).click();
  await expect(page.getByTestId("feed-total")).toContainText("newest first");
  await page.getByLabel("Location").fill("Anchorage");
  await expect(page.getByTestId("relax-location")).toBeVisible();

  const seen = await feedRequests();
  expect(seen.length).toBeGreaterThanOrEqual(5);
  for (const r of seen) expect(r).toMatch(/[?&]sort=(recent|score)(&|$)/);
  expect(seen.filter((r) => r.includes("sort=score")).map((r) => new URLSearchParams(r.split("?")[1]).get("page"))).toEqual(["1", "2"]);
  // the probe for the empty state asks for one row and still says how to sort
  expect(seen.some((r) => r.includes("page_size=1") && r.includes("sort=recent"))).toBe(true);
});

test("an unknown sort value in the URL falls back to newest first", async ({ page }) => {
  await page.goto("/?sort=alphabetical");
  await expect(page.getByRole("radio", { name: "Newest first" })).toBeChecked();
  await expect(page.getByTestId("posting-card")).toHaveCount(20);
  expectNewestFirst(await rows(page));
});

test("empty-state probing works under Best match and relaxing keeps the sort", async ({ page }) => {
  await page.goto("/?roles=security&location=Seattle&sort=score");
  const empty = page.getByTestId("empty-state");
  await expect(empty).toContainText("No Security postings in Seattle.");
  await expect(empty).toContainText("4 Security postings elsewhere");
  await page.getByTestId("relax-location").click();
  await expect(page).toHaveURL(/\/\?roles=security&sort=score$/);
  await expect(page.getByTestId("posting-card")).toHaveCount(4);
  expectBestMatchFirst(await rows(page));
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

test("a save made while the list is refreshing is not undone by the refresh", async ({ page }) => {
  // To Best match and straight back: the newest-first list is on screen again
  // while it is fetched again in the background.
  await page.getByRole("radio", { name: "Best match" }).click();
  await page.getByRole("radio", { name: "Newest first" }).click();
  const toggle = page
    .getByTestId("posting-card")
    .filter({ has: page.getByRole("button", { name: "Save", exact: true }) })
    .first()
    .getByTestId("save-toggle");
  const id = await toggle.locator("xpath=ancestor::article").getAttribute("data-posting-id");
  const mine = page.locator(`[data-posting-id="${id}"]`).getByTestId("save-toggle");
  await mine.click(); // lands before the background fetch comes back
  await expect(mine).toHaveAttribute("aria-pressed", "true");
  await page.waitForTimeout(1500); // the fetch has come back by now
  await expect(mine).toHaveAttribute("aria-pressed", "true");
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
