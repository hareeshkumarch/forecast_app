import { chromium } from "@playwright/test";

const BASE = process.env.BASE ?? "http://localhost:3000";
const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const WIDTHS = process.env.WIDTHS
  ? process.env.WIDTHS.split(",").map(Number)
  : [320, 375, 430, 768, 1024, 1280, 1366, 1440, 1920, 2560];

const PROBES = [
  ["shell width", "#how-it-works > div"],
  ["nav width", "nav"],
  ["nav height", "nav"],
  ["hero h1", "#top h1"],
  ["hero section h", "#top"],
  ["h2 how-it-works", "#how-it-works h2"],
  ["hero CTA height", '#top a[href="/dashboard"]'],
  ["step card", "#how-it-works .grid.gap-4 > div"],
  ["feature card", "#features .grid > div"],
  ["chart svg", 'svg[role="img"]'],
  ["section pad", "#how-it-works"],
];

const browser = await chromium.launch({ executablePath: CHROME });
const rows = [];

for (const width of WIDTHS) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.addStyleTag({ content: ".reveal{opacity:1 !important;transform:none !important}" });
  await page.waitForTimeout(150);

  const measured = await page.evaluate((probes) => {
    const out = {};
    const px = (v) => Math.round(parseFloat(v) || 0);
    for (const [label, sel] of probes) {
      const el = document.querySelector(sel);
      if (!el) {
        out[label] = null;
        continue;
      }
      const box = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      if (label.endsWith("height") || label === "hero section h") out[label] = Math.round(box.height);
      else if (label === "section pad") out[label] = `${px(cs.paddingTop)}/${px(cs.paddingBottom)}`;
      else if (label.startsWith("hero h1") || label.startsWith("h2"))
        out[label] = `${px(cs.fontSize)}px`;
      else if (label.endsWith("card")) out[label] = `${Math.round(box.width)}x${Math.round(box.height)}`;
      else out[label] = Math.round(box.width);
    }
    out["body scrollW"] = document.documentElement.scrollWidth;
    out["overflow"] = document.documentElement.scrollWidth > window.innerWidth ? "YES" : "no";
    return out;
  }, PROBES);

  rows.push({ width, ...measured });
  await page.close();
}

const cols = Object.keys(rows[0]);
const pad = (s, n) => String(s ?? "-").padEnd(n);
const widths = cols.map((c) => Math.max(c.length, ...rows.map((r) => String(r[c] ?? "-").length)) + 1);
console.log(cols.map((c, i) => pad(c, widths[i])).join("| "));
console.log(widths.map((w) => "-".repeat(w)).join("+-"));
for (const row of rows) console.log(cols.map((c, i) => pad(row[c], widths[i])).join("| "));

await browser.close();
