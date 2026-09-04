import { chromium } from "@playwright/test";

const BASE = process.env.BASE ?? "http://localhost:3000";
const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const SAMPLES = 40;
const VIEWPORT = { width: 1440, height: 900 };

const browser = await chromium.launch({ executablePath: CHROME });
const page = await browser.newPage({ viewport: VIEWPORT });
await page.goto(BASE, { waitUntil: "networkidle" });
await page.waitForSelector(".motion-ready", { timeout: 10_000 });

const track = page.locator('.scroll-track[data-stage="accuracy"]');
await track.scrollIntoViewIfNeeded();

const pin = await track.evaluate((el) => ({
  top: el.getBoundingClientRect().top + window.scrollY,
  travel: el.offsetHeight - window.innerHeight,
}));

const rows = [];
for (let i = 0; i <= SAMPLES; i += 1) {
  const at = i / SAMPLES;
  await page.evaluate((y) => window.scrollTo(0, y), pin.top + pin.travel * at);
  await page.waitForTimeout(60);
  rows.push({
    at,
    ...(await page.evaluate(() => {
      const wrap = document.querySelector(".accuracy-beats");
      const frame = wrap.getBoundingClientRect();
      const scrub =
        parseFloat(getComputedStyle(wrap.closest(".scroll-track")).getPropertyValue("--t")) || 0;

      // The line's box is the whole window, so the type is what has to be
      // measured — a box that is present says nothing about ink on screen.
      const typeOf = (el) => {
        const range = document.createRange();
        range.selectNodeContents(el);
        return range.getBoundingClientRect();
      };

      const beats = [...document.querySelectorAll(".accuracy-beat")].map((el) => {
        const box = typeOf(el);
        return {
          lit: Number(getComputedStyle(el).opacity),
          inside:
            Math.max(0, Math.min(box.bottom, frame.bottom) - Math.max(box.top, frame.top)) /
            Math.max(1, box.height),
          top: Math.round(box.top),
          bottom: Math.round(box.bottom),
          height: Math.round(box.height),
        };
      });

      const ticks = [...document.querySelectorAll(".accuracy-tick")].map((el) =>
        Number(getComputedStyle(el, "::after").opacity)
      );

      return {
        scrub,
        frame: Math.round(frame.height),
        width: Math.round(frame.width),
        beats,
        ticks,
      };
    })),
  });
}

const shown = (beat) => beat.lit * beat.inside;
const peak = rows[0].beats.map(() => 0);
const stillness = rows[0].beats.map(() => []);
let thinnest = Infinity;
let thinnestAt = null;
let drift = 0;
let mismatch = 0;
let overlap = 0;
let overlapAt = null;
let clipped = 0;

for (const row of rows) {
  const ink = row.beats.reduce((total, beat) => total + shown(beat), 0);
  if (ink < thinnest) {
    thinnest = ink;
    thinnestAt = row;
  }

  row.beats.forEach((beat, i) => {
    peak[i] = Math.max(peak[i], shown(beat));
    if (beat.lit > 0.99) stillness[i].push(beat.top);
    mismatch = Math.max(mismatch, Math.abs(beat.lit - (row.ticks[i] ?? 0)));
  });

  const lit = row.beats.filter((beat) => beat.lit > 0.02);
  for (const beat of lit) clipped = Math.max(clipped, 1 - beat.inside);
  for (let i = 0; i < lit.length; i += 1) {
    for (let j = i + 1; j < lit.length; j += 1) {
      const over = Math.min(lit[i].bottom, lit[j].bottom) - Math.max(lit[i].top, lit[j].top);
      if (over > overlap) {
        overlap = over;
        overlapAt = row;
      }
    }
  }
}

for (const tops of stillness) {
  if (tops.length > 1) drift = Math.max(drift, Math.max(...tops) - Math.min(...tops));
}

console.log(
  `window ${rows[0].width}x${rows[0].frame}px · lines ${rows[0].beats
    .map((beat) => `${beat.height}px`)
    .join(", ")}`
);
console.log("");
console.log("  at    --t    " + rows[0].beats.map((_, i) => `line ${i + 1}`.padEnd(9)).join("") + "ink");
for (const row of rows) {
  if (Math.round(row.at * SAMPLES) % 4 !== 0) continue;
  const ink = row.beats.map(shown);
  console.log(
    "  " +
      row.at.toFixed(2).padEnd(6) +
      row.scrub.toFixed(3).padEnd(7) +
      ink.map((value) => value.toFixed(3).padEnd(9)).join("") +
      ink.reduce((a, b) => a + b, 0).toFixed(3)
  );
}

const checks = [
  [
    peak.every((value) => value > 0.98),
    `every line is fully shown at some point     — dimmest peak ${Math.min(...peak).toFixed(3)}`,
  ],
  [
    thinnest > 0.85,
    `the window is never empty                   — least ink ${thinnest.toFixed(3)} at --t=${thinnestAt.scrub.toFixed(3)}`,
  ],
  [drift <= 1, `a line does not drift while it is lit       — ${drift}px`],
  [
    overlap <= 0,
    `no two lines are printed through each other — ${Math.max(0, overlap)}px${
      overlapAt ? ` at --t=${overlapAt.scrub.toFixed(3)}` : ""
    }`,
  ],
  [clipped < 0.02, `no lit line is cut off by the window        — ${(clipped * 100).toFixed(1)}% at most`],
  [mismatch < 0.02, `each tick is lit with its own line          — ${mismatch.toFixed(3)} apart at most`],
];

console.log("");
for (const [ok, line] of checks) console.log(`  ${ok ? "ok  " : "FAIL"} ${line}`);

const passed = checks.every(([ok]) => ok);
console.log("");
console.log(passed ? "PASS" : "FAIL");

await browser.close();
process.exit(passed ? 0 : 1);
