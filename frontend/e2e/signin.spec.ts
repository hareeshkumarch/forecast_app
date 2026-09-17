import { expect, test } from "@playwright/test";

test("a build with no sign-in configured sends /signin to the workspace", async ({ page }) => {
  await page.goto("/signin");

  await expect(page).toHaveURL(/\/dashboard$/);
});

test("the redirect leaves no sign-in screen behind it", async ({ page }) => {
  await page.goto("/signin");
  await page.waitForURL(/\/dashboard$/);

  await expect(page.getByRole("button", { name: "Continue with Google" })).toHaveCount(0);
});
