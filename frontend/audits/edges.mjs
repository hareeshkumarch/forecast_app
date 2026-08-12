import { chromium } from "@playwright/test";

const BASE = process.env.BASE ?? "http://localhost:3000";
const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

const browser = await chromium.launch({ executablePath: CHROME });
const found = [];
const note = (ok, label, detail = "") => {
  console.log(`  ${ok ? "ok  " : "EDGE"} ${label}${detail ? `  — ${detail}` : ""}`);
  if (!ok) found.push(label);
};

console.log("\nchart sequence");
{
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForTimeout(1800);
  const scales = await page.evaluate(() =>
    [...document.querySelectorAll("svg[role=img] .scape-bar")].map(
      (b) => +new DOMMatrixReadOnly(getComputedStyle(b).transform).d.toFixed(3),
    ),
  );
  const flat = scales.filter((s) => s < 0.99).length;
  note(flat === 0, "runs when the chart is in view at load", `${flat} bars still flat`);
  await page.close();
}
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(1800);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(1800);
  const flat = await page.evaluate(
    () =>
      [...document.querySelectorAll("svg[role=img] .scape-bar")].filter(
        (b) => new DOMMatrixReadOnly(getComputedStyle(b).transform).d < 0.99,
      ).length,
  );
  note(flat === 0, "survives a fast scroll past and back", `${flat} bars still flat`);
  await page.close();
}

console.log("\nnav indicator");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });
  const frames = [];
  // A later item, so a correct first placement is nowhere near x=0. The first
  // nav item legitimately sits at offsetLeft 0 and would pass trivially.
  await page.click('nav a[href="#accuracy"]');
  for (let i = 0; i < 12; i++) {
    frames.push(
      await page.evaluate(() => {
        const el = document.querySelector(".nav-indicator");
        const m = new DOMMatrixReadOnly(getComputedStyle(el).transform);
        return { x: +m.e.toFixed(1), o: +getComputedStyle(el).opacity };
      }),
    );
    await page.waitForTimeout(25);
  }
  const firstVisible = frames.find((f) => f.o > 0.05);
  note(
    !firstVisible || firstVisible.x > 20,
    "first appearance does not slide in from x=0",
    `first visible at x=${firstVisible?.x}`,
  );

  const before = await page.evaluate(
    () => new DOMMatrixReadOnly(getComputedStyle(document.querySelector(".nav-indicator")).transform).e,
  );
  await page.setViewportSize({ width: 1100, height: 900 });
  await page.waitForTimeout(400);
  // Which item is active may legitimately change during a resize, so the
  // indicator is checked against whichever one is current, not a fixed one.
  const after = await page.evaluate(() => {
    const el = document.querySelector(".nav-indicator");
    const link = document.querySelector('nav [aria-current="page"]');
    return {
      x: new DOMMatrixReadOnly(getComputedStyle(el).transform).e,
      target: link?.offsetLeft ?? -1,
      on: link?.textContent?.trim() ?? "none",
    };
  });
  note(Math.abs(after.x - after.target) < 2, "tracks its item across a resize", `${before} -> ${after.x}, "${after.on}" at ${after.target}`);
  await page.close();
}

console.log("\ntouch and keyboard");
{
  const page = await browser.newPage({
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    isMobile: true,
  });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForTimeout(1700);
  const box = await page.evaluate(() => {
    const bars = [...document.querySelectorAll("svg[role=img] .scape-bar")];
    const r = bars[Math.floor(bars.length / 2)].getBoundingClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  await page.touchscreen.tap(box.x, box.y);
  await page.waitForTimeout(250);
  const readout = await page.locator("p.scape-readout").innerText();
  note(!/Hover any week/i.test(readout), "a tap reads out a week on touch", `"${readout.trim()}"`);

  const reachable = await page.evaluate(
    () => document.querySelector("svg[role=img]")?.getAttribute("tabindex") === "0",
  );
  note(reachable, "the chart itself takes focus");
  await page.close();
}

{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForTimeout(1700);
  await page.evaluate(() => document.querySelector("svg[role=img]").focus());
  for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowRight");
  await page.waitForTimeout(150);
  const spoken = await page.locator("p.sr-only").innerText();
  const marker = await page.evaluate(() => document.querySelectorAll(".scape-marker").length);
  note(/week|ago|units/i.test(spoken), "arrow keys move and announce a week", `"${spoken.trim()}"`);
  note(marker === 1, "the selected column is marked", `${marker} marker`);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(120);
  note(
    (await page.evaluate(() => document.querySelectorAll(".scape-marker").length)) === 0,
    "escape clears the selection",
  );
  await page.close();
}

console.log("\nscreen readers");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });
  const live = await page.evaluate(() => {
    const el = document.querySelector("p.scape-readout");
    return { live: el?.getAttribute("aria-live"), atomic: el?.getAttribute("aria-atomic") };
  });
  note(
    live.live !== "polite" || live.atomic === "true",
    "hover readout does not spam assistive tech",
    `aria-live=${live.live}`,
  );
  await page.close();
}

console.log("\nreduced motion");
{
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, reducedMotion: "reduce" });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.waitForTimeout(400);
  const r = await page.evaluate(() => {
    const bars = [...document.querySelectorAll("svg[role=img] .scape-bar")];
    const hidden = [...document.querySelectorAll(".reveal")].filter(
      (e) => +getComputedStyle(e).opacity < 0.99,
    ).length;
    return {
      flat: bars.filter((b) => new DOMMatrixReadOnly(getComputedStyle(b).transform).d < 0.99).length,
      hidden,
      infinite: [...document.querySelectorAll("*")].filter((e) => {
        const cs = getComputedStyle(e);
        return cs.animationIterationCount === "infinite" && parseFloat(cs.animationDuration) > 0.1;
      }).length,
    };
  });
  note(r.flat === 0 && r.hidden === 0, "static page is complete", `${r.flat} flat, ${r.hidden} hidden`);
  note(r.infinite === 0, "no infinite animation keeps running", `${r.infinite} looping`);
  await page.close();
}

console.log(found.length ? `\n${found.length} EDGE CASES` : "\nno edge cases found");
found.forEach((f) => console.log(`  - ${f}`));
await browser.close();
