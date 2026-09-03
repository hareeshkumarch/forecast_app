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

test("the primary call to action opens sign in", async ({ page }) => {
  await page.goto("/");

  // The href, not the landing URL. This suite builds without a Supabase
  // project, and such a build redirects /signin to /dashboard rather than
  // showing a sign-in screen it cannot honour — so following the click here
  // would assert that redirect rather than where the button points.
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
    // "Everything a planner needs, and nothing they do not." used to sit here.
    // It headed the feature-card grid, and that grid went when the page
    // dropped its cards and charts for something with visible motion.
    "Know what changed, why it matters, and what to do next.",
    "A range tells you more than a perfect-looking line.",
    // The accuracy figure counts up the first time it is scrolled to, so this
    // heading's name is whatever the count is currently showing. Matching the
    // finished sentence would deadlock: the count does not start until the
    // heading is in view, and the heading cannot be scrolled to until it
    // matches. The words either side of the number are what is stable.
    /of the sales it had never seen/,
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

/*
 * The build in "how it works" is pinned and scrubbed rather than played: the
 * scroll past the section is what moves it. These cover the two ends of that —
 * that scrolling actually advances it, and that a visitor who is not being
 * scrubbed through it gets the finished drawing instead of an empty frame.
 */
test("the build advances with the scroll and settles before the pin lets go", async ({ page }) => {
  await page.goto("/");
  const track = page.locator(".scroll-track");
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

  // Only most of the way: the last of the travel deliberately holds the
  // finished chart, so the drawing has to be complete before the end.
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

  const track = page.locator(".scroll-track");
  const finished = await track.evaluate((node) => {
    const styles = getComputedStyle(node);
    return ["--t-fill", "--t-read", "--t-build", "--t-ahead"].map((name) =>
      Number(styles.getPropertyValue(name)),
    );
  });
  expect(finished).toEqual([1, 1, 1, 1]);

  // Three screens of pinned scroll with nothing pinned in them would be three
  // screens of nothing.
  const height = await track.evaluate((node: HTMLElement) => node.offsetHeight);
  expect(height).toBeLessThan(page.viewportSize()!.height * 2);

  // Every step keeps its sentence, rather than waiting for a scrub to open it.
  for (const step of await page.locator(".pipeline-detail").all()) {
    const box = await step.boundingBox();
    expect(box!.height).toBeGreaterThan(0);
  }

  await context.close();
});

/*
 * Two sections wrote their colours literally and so stayed on white paper
 * while the rest of the page went dark. The `.forecast-landing` check above
 * passed the whole time, because the canvas underneath them did flip.
 */
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
        // A slab, not a chip: the primary button is light in this theme on
        // purpose, and it is nothing like this size.
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

  // No `.motion-ready`, so nothing was ever hidden and nothing has to animate
  // back into view.
  await expect(page.locator(".motion-ready")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Know what changed, why it matters, and what to do next." }),
  ).toBeVisible();

  await context.close();
});

/*
 * The pinned section grows by three screens when it comes alive. Anything that
 * scrolls to the hash before that height is settled — which is what the dev
 * server does, and what `audits/track-a.mjs` measures on a cold hash — leaves
 * every anchor below the section thousands of pixels off. This holds the
 * property from the reader's end, whoever does the scrolling.
 */
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

/*
 * The landing page was light by construction, and the one element that read
 * the theme tokens while the rest did not gave a visitor on a dark OS two
 * near-black smudges behind a light headline. These three cover the shape of
 * that bug from both ends: the whole page has to move together, and it has to
 * move for the OS as well as for the button.
 */
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
  // The chart is drawn in SVG with its own palette, which is exactly where a
  // half-themed page shows: the frame flips and the drawing inside does not.
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

  // Survives a reload, and without a flash: the bootstrap script in the
  // document head sets the theme before anything paints, so the very first
  // frame is already dark.
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
  // The full label wrapped to two lines and spilled out of a fixed-height pill
  // below roughly 360px, which is where the older Android widths sit.
  await page.setViewportSize({ width: 320, height: 800 });
  await page.goto("/");

  const cta = page.getByRole("navigation", { name: "Sections" }).getByRole("link", {
    name: "Open the dashboard",
  });

  // The pill is collapsed to nothing until the hero has been scrolled past —
  // it is the nav's copy of a call to action the hero is still showing. There
  // is no pill to measure before that.
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

  // Below the large breakpoint the list is display:none and there is nothing
  // to measure — which is the "only appears once it has room" the name means.
  for (const link of await nav.locator("[data-section]:visible").all()) {
    const box = await link.boundingBox();
    expect(box, "every section link has a box").not.toBeNull();

    // Measured against the link's own line-height rather than a fixed pixel
    // count. The type scale here is fluid, so a single line is a different
    // number of pixels at every width — a constant threshold only ever
    // described one of them, and grew stale the moment the scale changed.
    const onOneLine = await link.evaluate((node) => {
      const styles = getComputedStyle(node);
      const box = node.getBoundingClientRect();
      const frame =
        parseFloat(styles.paddingTop) +
        parseFloat(styles.paddingBottom) +
        parseFloat(styles.borderTopWidth) +
        parseFloat(styles.borderBottomWidth);
      // A second line adds a whole line-height, so half of one is a margin no
      // single-line box can cross and no wrapped box can stay under.
      return box.height - frame <= parseFloat(styles.lineHeight) * 1.5;
    });
    expect(onOneLine, "every section link sits on one line").toBe(true);
  }
});
