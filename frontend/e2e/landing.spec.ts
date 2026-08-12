import { expect, test } from "@playwright/test";

/*
 * The landing page is the first thing anyone sees, and the one page that is
 * fully static — so what matters is that it composes at every width and that
 * its scroll animation is an enhancement rather than a prerequisite for
 * reading it.
 */

test("the landing page is the root and the app has moved to /dashboard", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1 })).toContainText("See your demand");
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
    "From a spreadsheet to a plan in three steps.",
    "Everything a planner needs, and nothing they do not.",
    "A range tells you more than a perfect-looking line.",
    "Right about 94% of the sales it had never seen.",
    "See what is coming next.",
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

test("with reduced motion the page is composed from the first paint", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();

  await page.goto("/");

  // No `.motion-ready`, so nothing was ever hidden and nothing has to animate
  // back into view.
  await expect(page.locator(".motion-ready")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Everything a planner needs, and nothing they do not." }),
  ).toBeVisible();

  await context.close();
});

test("the header call to action fits its pill on the narrowest phones", async ({ page }) => {
  // The full label wrapped to two lines and spilled out of a fixed-height pill
  // below roughly 360px, which is where the older Android widths sit.
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/");

  const cta = page.locator("header").getByRole("link", { name: "Open the dashboard" });
  await expect(cta).toBeVisible();

  const fits = await cta.evaluate((node) => node.scrollHeight <= node.clientHeight);
  expect(fits).toBe(true);
});

test("the section nav only appears once it has room for one line", async ({ page }) => {
  await page.goto("/");

  const nav = page.getByRole("navigation", { name: "Sections" });
  if (!(await nav.isVisible())) return;

  for (const link of await nav.getByRole("link").all()) {
    const box = await link.boundingBox();
    expect(box, "every section link has a box").not.toBeNull();
    // One line of text at this size is ~20px; two would clear 30.
    expect(box!.height).toBeLessThan(30);
  }
});
