import { chromium } from "@playwright/test";

const BASE = process.env.BASE ?? "http://localhost:3000";
const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

const browser = await chromium.launch({ executablePath: CHROME });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
await page.goto(BASE, { waitUntil: "networkidle" });
await page.waitForTimeout(1700);

const box = await page.evaluate(() => {
  const bars = [...document.querySelectorAll("svg[role=img] .scape-bar")];
  const r = bars[Math.floor(bars.length / 2)].getBoundingClientRect();
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
});

const read = () =>
  page.evaluate(() => {
    const svg = document.querySelector("svg[role=img]");
    const cs = getComputedStyle(svg);
    return {
      focused: document.activeElement === svg,
      matchesFocus: svg.matches(":focus"),
      matchesFocusVisible: svg.matches(":focus-visible"),
      outline: `${cs.outlineStyle} ${cs.outlineWidth} ${cs.outlineColor}`,
      tapHighlight: cs.webkitTapHighlightColor ?? "(none)",
      userSelect: cs.userSelect,
      selection: String(window.getSelection() ?? ""),
      selectionRanges: window.getSelection()?.rangeCount ?? 0,
    };
  });

console.log("\nbefore any interaction");
console.log(" ", JSON.stringify(await read()));

await page.mouse.click(box.x, box.y);
await page.waitForTimeout(200);
console.log("\nafter a plain click on a bar");
console.log(" ", JSON.stringify(await read()));

await page.mouse.move(box.x, box.y);
await page.mouse.down();
await page.mouse.move(box.x + 40, box.y + 20, { steps: 5 });
await page.mouse.up();
await page.waitForTimeout(200);
console.log("\nafter a small drag across the chart");
console.log(" ", JSON.stringify(await read()));
await page.screenshot({ path: "audits/out-drag.png", clip: { x: box.x - 260, y: box.y - 160, width: 520, height: 320 } });

await page.evaluate(() => window.getSelection()?.removeAllRanges());
await page.keyboard.press("Tab");
await page.waitForTimeout(120);
await page.evaluate(() => document.querySelector("svg[role=img]").focus());
await page.waitForTimeout(150);
console.log("\nafter focusing from the keyboard");
console.log(" ", JSON.stringify(await read()));
await page.screenshot({ path: "audits/out-keyboard.png", clip: { x: box.x - 260, y: box.y - 160, width: 520, height: 320 } });

const touch = await browser.newPage({
  viewport: { width: 390, height: 844 },
  hasTouch: true,
  isMobile: true,
});
await touch.goto(BASE, { waitUntil: "networkidle" });
await touch.waitForTimeout(1700);
const tbox = await touch.evaluate(() => {
  const bars = [...document.querySelectorAll("svg[role=img] .scape-bar")];
  const r = bars[Math.floor(bars.length / 2)].getBoundingClientRect();
  return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
});
await touch.touchscreen.tap(tbox.x, tbox.y);
await touch.waitForTimeout(200);
console.log("\nafter a tap on touch");
console.log(
  " ",
  JSON.stringify(
    await touch.evaluate(() => {
      const svg = document.querySelector("svg[role=img]");
      const cs = getComputedStyle(svg);
      return {
        matchesFocus: svg.matches(":focus"),
        matchesFocusVisible: svg.matches(":focus-visible"),
        outline: `${cs.outlineStyle} ${cs.outlineWidth} ${cs.outlineColor}`,
        tapHighlight: cs.webkitTapHighlightColor ?? "(none)",
      };
    }),
  ),
);

await browser.close();
