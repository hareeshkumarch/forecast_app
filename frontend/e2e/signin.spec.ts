import { expect, test } from "@playwright/test";

test("sign in is clear, validated, and keeps a demo path", async ({ page }) => {
  await page.goto("/signin");

  await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Enter a valid work email.", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Explore the live workspace" })).toHaveAttribute(
    "href",
    "/dashboard",
  );
});

test("sign in does not overflow a phone viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/signin");

  const sizes = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));

  expect(sizes.scrollWidth).toBeLessThanOrEqual(sizes.clientWidth);
});
