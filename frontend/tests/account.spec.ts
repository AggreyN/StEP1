// Deleting the account from the Profile screen.
import { expect, test } from "@playwright/test";
import { PASSWORD, errorNote, freshEmail, signIn } from "./helpers";

async function onboard(page: import("@playwright/test").Page, email: string) {
  await signIn(page, email, "register");
  await expect(page).toHaveURL(/\/onboarding$/);
  await page.getByLabel("Major").fill("Information Science");
  for (const n of ["+ Security", "+ Software Engineering", "+ Research"]) {
    await page.getByRole("button", { name: n }).click();
  }
  await page.getByTestId("submit-profile").click();
  await expect(page).toHaveURL(/\/$/, { timeout: 15_000 });
  await expect(page.getByTestId("posting-card").first()).toBeVisible();
}

test("delete my account: says what goes, needs the password and a deliberate confirm", async ({ page }) => {
  const email = freshEmail("delete");
  await onboard(page, email);

  // leave something behind to be deleted
  await page.getByTestId("posting-card").first().getByTestId("apply-button").click();
  await page.getByTestId("confirm-applied").click();
  await expect(page.getByTestId("posting-card").first().getByTestId("application-link")).toBeVisible();

  await page.goto("/onboarding");
  const section = page.getByRole("region", { name: "Delete my account" });
  await expect(section).toContainText("your resume file and all of your history");
  // it is the last thing on the screen, below the form
  const formBox = await page.getByTestId("submit-profile").boundingBox();
  const sectionBox = await section.boundingBox();
  expect(sectionBox!.y).toBeGreaterThan(formBox!.y);

  await page.getByTestId("open-delete").click();
  const dialog = page.getByRole("dialog", { name: "Delete your account?" });
  await expect(dialog.getByTestId("delete-list").getByRole("listitem")).toHaveText([
    "your account and sign-in",
    "your profile and ranked fields",
    "your resume file, and the text and skills read from it",
    "your saved postings",
    "every application you tracked, with its events and notes",
  ]);
  const confirm = dialog.getByTestId("confirm-delete");
  await expect(confirm).toBeDisabled();
  await dialog.getByLabel("Your password").fill("not-my-password");
  await expect(confirm).toBeDisabled(); // password alone is not enough
  await dialog.getByRole("checkbox").check();
  await expect(confirm).toBeEnabled();

  // wrong password: the API's words, and nothing is deleted
  await confirm.click();
  await expect(errorNote(page)).toHaveText("Password is incorrect.");
  await expect(page).toHaveURL(/\/onboarding$/);
  expect(await page.evaluate(() => localStorage.getItem("step1.token"))).not.toBeNull();

  // backing out keeps the account, and the form is blank next time
  await dialog.getByRole("button", { name: "Keep my account" }).click();
  await expect(dialog).toBeHidden();
  await page.getByTestId("open-delete").click();
  await expect(dialog.getByLabel("Your password")).toHaveValue("");
  await expect(dialog.getByRole("checkbox")).not.toBeChecked();

  // the right password
  await dialog.getByLabel("Your password").fill(PASSWORD);
  await dialog.getByRole("checkbox").check();
  await confirm.click();
  await expect(page).toHaveURL(/\/login\?deleted=1$/);
  await expect(page.getByTestId("deleted-notice")).toHaveText("Your account and everything in it have been deleted.");
  expect(
    await page.evaluate(() => Object.keys(localStorage).filter((k) => k.startsWith("step1.") && !k.startsWith("step1.mock.")))
  ).toEqual([]);

  // signed out for real
  await page.goto("/applications");
  await expect(page).toHaveURL(/\/login/);

  // and the data is gone: the same email is a brand-new account with no profile
  await signIn(page, email);
  await expect(page).toHaveURL(/\/onboarding$/);
  await expect(page.getByLabel("Major")).toHaveValue("");
  await expect(page.getByTestId("ranked-interest")).toHaveCount(0);
});

test("a rate-limited delete shows the API's message and keeps the session", async ({ page }) => {
  await onboard(page, freshEmail("delete429"));
  await page.goto("/onboarding");
  await page.getByTestId("open-delete").click();
  const dialog = page.getByRole("dialog", { name: "Delete your account?" });
  await dialog.getByLabel("Your password").fill(PASSWORD);
  await dialog.getByRole("checkbox").check();
  await page.evaluate(() => localStorage.setItem("step1.mock.fail", "429 DELETE /me"));
  await dialog.getByTestId("confirm-delete").click();
  await expect(errorNote(page)).toHaveText("Too many attempts. Wait a minute and try again.");
  await expect(page).toHaveURL(/\/onboarding$/);
  expect(await page.evaluate(() => localStorage.getItem("step1.token"))).not.toBeNull();
});
