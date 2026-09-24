import { expect, test } from "@playwright/test";

test("scenario preview responds to assumptions and live motion preferences", async ({ page }) => {
  await page.goto("/");
  const preview = page.locator("#scenario-preview");
  await preview.scrollIntoViewIfNeeded();
  await preview.getByRole("button", { name: "Demand lift" }).click();
  await expect(preview.getByRole("button", { name: "Demand lift" })).toHaveAttribute("aria-pressed", "true");
  await expect(preview.getByRole("img")).toHaveAttribute("aria-label", /Demand lift: week 1, 98 units/);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.locator(".forecast-landing")).not.toHaveClass(/motion-ready/);
  await expect(page.locator(".scroll-track--live")).toHaveCount(0);
  const duration = await preview.locator(".scenario-bar").first().evaluate(
    (node) => parseFloat(getComputedStyle(node).transitionDuration),
  );
  expect(duration).toBeLessThanOrEqual(0.001);
  await preview.getByRole("button", { name: "Softer demand" }).click();
  await expect(preview.getByRole("img")).toHaveAttribute("aria-label", /Softer demand: week 1, 70 units/);
});

test("the landing page is the root and the app has moved to /dashboard", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1 })).toContainText("See your demand");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeHidden();
});

test("the primary call to action opens sign in", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("link", { name: "Start forecasting" }).first()).toHaveAttribute(
    "href",
    "/signin",
  );
});

test("the live workspace remains available as a demo", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("link", { name: "Open the dashboard" }).click();
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
  test.setTimeout(60_000);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

  for (const heading of [
    "From a spreadsheet to a plan in three steps.",
    "Know what changed, why it matters, and what to do next.",
    "A range tells you more than a perfect-looking line.",
    /of the sales it had never seen/,
    "See what is coming next.",
  ]) {
    const target = page.getByRole("heading", { name: heading });
    await target.scrollIntoViewIfNeeded();
    await expect(target).toBeVisible();
    await expect
      .poll(() => target.evaluate((node) => Number(getComputedStyle(node).opacity)), {
        timeout: 4000,
      })
      .toBeGreaterThan(0.9);
  }
});

test("the build advances with the scroll and settles before the pin lets go", async ({ page }) => {
  await page.goto("/");
  const track = page.locator('.scroll-track[data-stage="build"]');
  await expect(track).toHaveClass(/scroll-track--live/);

  const read = () =>
    track.evaluate((node) => {
      const styles = getComputedStyle(node);
      return {
        step: node.dataset.step,
        fill: Number(styles.getPropertyValue("--t-fill")),
        build: Number(styles.getPropertyValue("--t-build")),
        ahead: Number(styles.getPropertyValue("--t-ahead")),
      };
    });

  const frame = await track.evaluate((node: HTMLElement) => ({
    top: node.getBoundingClientRect().top + window.scrollY,
    travel: node.offsetHeight - (node.firstElementChild as HTMLElement).offsetHeight,
  }));

  await page.evaluate((y) => window.scrollTo(0, y), frame.top - 200);
  await expect.poll(async () => (await read()).build).toBe(0);
  expect((await read()).step).toBe("0");

  await page.evaluate((y) => window.scrollTo(0, y), frame.top + frame.travel * 0.9);
  await expect.poll(async () => (await read()).ahead).toBe(1);

  const settled = await read();
  expect(settled.fill).toBe(1);
  expect(settled.build).toBe(1);
  expect(settled.step).toBe("2");
});

test("without the scrub the build is already drawn and the section is one screen", async ({
  browser,
}) => {
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();
  await page.goto("/");

  await expect(page.locator(".scroll-track--live")).toHaveCount(0);

  const track = page.locator('.scroll-track[data-stage="build"]');
  const finished = await track.evaluate((node) => {
    const styles = getComputedStyle(node);
    return ["--t-fill", "--t-read", "--t-build", "--t-ahead"].map((name) =>
      Number(styles.getPropertyValue(name)),
    );
  });
  expect(finished).toEqual([1, 1, 1, 1]);

  const height = await track.evaluate((node: HTMLElement) => node.offsetHeight);
  expect(height).toBeLessThan(page.viewportSize()!.height * 2);

  for (const step of await page.locator(".pipeline-detail").all()) {
    const box = await step.boundingBox();
    expect(box!.height).toBeGreaterThan(0);
  }

  await context.close();
});

test("no section stays light when the page goes dark", async ({ browser }) => {
  const context = await browser.newContext({ colorScheme: "dark" });
  const page = await context.newPage();
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  const pale = await page.evaluate(() => {
    const luminance = (color: string) => {
      const parts = color.match(/[\d.]+/g)?.map(Number) ?? [];
      const [r, g, b, alpha = 1] = parts;
      if (alpha < 0.9 || r === undefined) return null;
      return (0.2126 * r! + 0.7152 * g! + 0.0722 * b!) / 255;
    };

    return [...document.querySelectorAll<HTMLElement>(".forecast-landing *")]
      .filter((node) => {
        const box = node.getBoundingClientRect();
        return box.width > 300 && box.height > 200;
      })
      .map((node) => ({
        tag: `${node.tagName.toLowerCase()}.${node.className.toString().split(" ")[0]}`,
        light: luminance(getComputedStyle(node).backgroundColor),
      }))
      .filter((entry) => entry.light !== null && entry.light > 0.6)
      .map((entry) => entry.tag);
  });

  expect(pale).toEqual([]);
  await context.close();
});

test("with reduced motion the page is composed from the first paint", async ({ browser }) => {
  const context = await browser.newContext({ reducedMotion: "reduce" });
  const page = await context.newPage();

  await page.goto("/");

  await expect(page.locator(".motion-ready")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Know what changed, why it matters, and what to do next." }),
  ).toBeVisible();

  await context.close();
});

test("a cold link to a section below the pinned one still lands on it", async ({ page }) => {
  await page.goto("/#compare");
  const heading = page.getByRole("heading", {
    name: "A range tells you more than a perfect-looking line.",
  });

  await expect
    .poll(async () => {
      const box = await heading.boundingBox();
      return box ? Math.round(box.y) : 99_999;
    })
    .toBeLessThan(page.viewportSize()!.height);
});

test("the primary call to action fits on the narrowest phones", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/");

  const cta = page.getByRole("link", { name: "Start forecasting" }).first();
  await expect(cta).toBeVisible();

  const fits = await cta.evaluate((node) => node.scrollHeight <= node.clientHeight);
  expect(fits).toBe(true);
});

test("the landing page follows the operating system's colour scheme", async ({ browser }) => {
  const context = await browser.newContext({ colorScheme: "dark" });
  const page = await context.newPage();
  await page.goto("/");

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  const canvas = await page
    .locator(".forecast-landing")
    .evaluate((node) => getComputedStyle(node).backgroundColor);
  expect(canvas).toBe("rgb(17, 21, 18)");

  await context.close();
});

test("the theme control switches the page and is remembered", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  const inkOf = (selector: string) =>
    page.locator(selector).first().evaluate((node) => getComputedStyle(node).backgroundColor);

  const litPage = await inkOf(".forecast-landing");
  const litChart = await page
    .locator('.scape-bar[data-tone="history"][data-row="0"] polygon')
    .first()
    .evaluate((node) => getComputedStyle(node).fill);

  await page.getByRole("button", { name: "Switch between light and dark" }).click();

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await inkOf(".forecast-landing")).not.toBe(litPage);
  expect(
    await page
      .locator('.scape-bar[data-tone="history"][data-row="0"] polygon')
      .first()
      .evaluate((node) => getComputedStyle(node).fill),
  ).not.toBe(litChart);

  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("the choice made on the landing page is the one the dashboard opens in", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Switch between light and dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");

  await page.goto("/dashboard");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("the nav call to action fits its pill on the narrowest phones", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/");

  const cta = page.getByRole("navigation", { name: "Sections" }).getByRole("link", {
    name: "Open the dashboard",
  });

  await expect(cta).toBeHidden();
  await page.evaluate(() => window.scrollTo(0, 900));
  await expect(cta).toBeVisible();

  const fits = await cta.evaluate((node) => node.scrollHeight <= node.clientHeight);
  expect(fits).toBe(true);
});

test("the section nav only appears once it has room for one line", async ({ page }) => {
  await page.goto("/");

  const nav = page.getByRole("navigation", { name: "Sections" });
  const sectionLinks = nav.locator("ul").first().getByRole("link");
  if (!(await sectionLinks.first().isVisible())) return;

  for (const link of await nav.locator("[data-section]:visible").all()) {
    const box = await link.boundingBox();
    expect(box, "every section link has a box").not.toBeNull();

    const onOneLine = await link.evaluate((node) => {
      const styles = getComputedStyle(node);
      const box = node.getBoundingClientRect();
      const frame =
        parseFloat(styles.paddingTop) +
        parseFloat(styles.paddingBottom) +
        parseFloat(styles.borderTopWidth) +
        parseFloat(styles.borderBottomWidth);
      return box.height - frame <= parseFloat(styles.lineHeight) * 1.5;
    });
    expect(onOneLine, "every section link sits on one line").toBe(true);
  }
});
