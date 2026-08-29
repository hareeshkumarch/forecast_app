import { expect, test } from "@playwright/test";

/*
 * Sign-in is configured at build time, from NEXT_PUBLIC_SUPABASE_URL and
 * NEXT_PUBLIC_SUPABASE_ANON_KEY, and this suite deliberately builds without
 * them — the same shape as local development, and a deployment the product
 * supports on purpose: a missing key leaves the app open rather than broken.
 *
 * So what there is to assert here is the unconfigured build's own promise:
 * /signin does not sit there showing a Google button that cannot work. It
 * sends you to the workspace instead, and it does it before anything is
 * painted, so nobody sees a screen offering something this build cannot do.
 *
 * The signed-in screen itself — the Google handoff, and the notice that new
 * accounts are reviewed before they see anything — is not reachable from a
 * build with no project behind it, and is not covered here.
 */

test("a build with no sign-in configured sends /signin to the workspace", async ({ page }) => {
  await page.goto("/signin");

  await expect(page).toHaveURL(/\/dashboard$/);
});

test("the redirect leaves no sign-in screen behind it", async ({ page }) => {
  await page.goto("/signin");
  await page.waitForURL(/\/dashboard$/);

  await expect(page.getByRole("button", { name: "Continue with Google" })).toHaveCount(0);
});
