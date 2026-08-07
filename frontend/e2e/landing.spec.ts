import { expect, test } from "@playwright/test";

/*
 * The landing page is the first thing anyone sees, and the one page that is
 * fully static — so what matters is that it composes at every width and that
 * its scroll animation is an enhancement rather than a prerequisite for
 * reading it.
 */

test("the landing page is the root and the app has moved to /dashboard", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1 })).toContainText("Nothing about the fit");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeHidden();
});

test("the primary call to action opens the dashboard", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("link", { name: "Open the dashboard" }).first().click();
  await expect(page).toHaveURL(/\/dashboard$/);
});

test("it never scrolls sideways, at any width", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  const { scrollWidth, clientWidth } = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));

  expect(scrollWidth).toBeLessThanOrEqual(clientWidth);
});

test("every section is readable once scrolled to", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  for (const heading of [
    "Three steps from raw history to a ranked forecast.",
    "Backtested first, trusted second.",
    "Ten forecasts, every run.",
    "Twelve ways in.",
    "See what it picks for your data.",
  ]) {
    const target = page.getByRole("heading", { name: heading });
    await target.scrollIntoViewIfNeeded();
    await expect(target).toBeVisible();
    // Revealed, not merely present: a stuck observer would leave it at zero.
    await expect
      .poll(() => target.evaluate((node) => Number(getComputedStyle(node).opacity)), {
        timeout: 4000,
      })
      .toBeGreaterThan(0.9);
  }
});

test("the header stays put and tracks how far down the page you are", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  const header = page.locator("header").first();
  const rule = header.locator("div[aria-hidden]").last();

  const scaleX = () =>
    rule.evaluate((node) => new DOMMatrixReadOnly(getComputedStyle(node).transform).a);

  expect(await scaleX()).toBeCloseTo(0, 1);

  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await expect.poll(scaleX, { timeout: 4000 }).toBeGreaterThan(0.9);

  // Sticky, not scrolled away with the page — `relative` here would silently
  // win over `sticky` through twMerge and nobody would notice.
  expect((await header.boundingBox())?.y ?? -1).toBeCloseTo(0, 0);
});

test("with reduced motion the page is composed from the first paint", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();

  await page.goto("/");

  // No `.motion-ready`, so nothing was ever hidden and nothing has to animate
  // back into view.
  await expect(page.locator(".motion-ready")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Twelve ways in." })).toBeVisible();

  await context.close();
});
