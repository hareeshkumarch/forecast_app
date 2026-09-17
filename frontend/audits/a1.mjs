import { chromium } from "@playwright/test";
import { PNG } from "pngjs";

const BASE = process.env.BASE ?? "http://localhost:3000";
const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";
const WIDTHS = [320, 375, 414, 640, 768, 1024, 1280, 1366, 1440, 1512, 1680, 1920, 2240, 2560];

const browser = await chromium.launch({ executablePath: CHROME });
const failures = [];

for (const width of WIDTHS) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.addStyleTag({
    content:
      ".reveal{opacity:1 !important;transform:none !important;filter:none !important}" +
      ".scroll-pin{position:static !important}" +
      ".pipeline-detail{grid-template-rows:1fr !important;opacity:1 !important}",
  });
  await page.waitForTimeout(120);

  const blocks = await page.evaluate(() => {
    const out = [];
    for (const el of document.querySelectorAll("h1,h2,h3,p,span,a,li,div")) {
      if (!el.childNodes.length) continue;
      if (![...el.childNodes].every((n) => n.nodeType === 3)) continue;
      if (!el.textContent.trim()) continue;
      const range = document.createRange();
      range.selectNodeContents(el);
      const rects = [...range.getClientRects()].filter((r) => r.height > 2 && r.width > 2);
      const tops = [...new Set(rects.map((r) => Math.round(r.top)))];
      if (tops.length < 2) continue;
      const r = el.getBoundingClientRect();
      out.push({
        text: el.textContent.trim().replace(/\s+/g, " ").slice(0, 44),
        tag: el.tagName,
        lines: tops.length,
        box: {
          top: r.top + window.scrollY,
          bottom: r.bottom + window.scrollY,
          left: r.left,
          right: r.right,
        },
      });
    }
    return out;
  });

  const shot = await page.screenshot({ fullPage: true });
  const png = PNG.sync.read(shot);
  const dpr = png.width / width;

  for (const b of blocks) {
    const x0 = Math.max(0, Math.floor(b.box.left * dpr));
    const x1 = Math.min(png.width, Math.ceil(b.box.right * dpr));
    const pad = Math.ceil(((b.box.bottom - b.box.top) / b.lines) * dpr);
    const y0 = Math.max(0, Math.floor(b.box.top * dpr) - pad);
    const y1 = Math.min(png.height, Math.ceil(b.box.bottom * dpr) + pad);
    if (x1 - x0 < 4 || y1 - y0 < 4) continue;

    const histogram = new Map();
    for (let y = y0; y < y1; y += 2) {
      for (let x = x0; x < x1; x += 2) {
        const i = (png.width * y + x) << 2;
        const key = (png.data[i] << 16) | (png.data[i + 1] << 8) | png.data[i + 2];
        histogram.set(key, (histogram.get(key) ?? 0) + 1);
      }
    }
    let modal = 0;
    let best = -1;
    for (const [key, count] of histogram) if (count > best) [modal, best] = [key, count];
    const bg = [(modal >> 16) & 255, (modal >> 8) & 255, modal & 255];

    const inked = [];
    for (let y = y0; y < y1; y++) {
      let dark = 0;
      for (let x = x0; x < x1; x++) {
        const i = (png.width * y + x) << 2;
        const d =
          Math.abs(png.data[i] - bg[0]) +
          Math.abs(png.data[i + 1] - bg[1]) +
          Math.abs(png.data[i + 2] - bg[2]);
        if (d > 100) dark++;
      }
      inked.push(dark > 0);
    }

    let bands = 0;
    for (let i = 0; i < inked.length; i++) if (inked[i] && !inked[i - 1]) bands++;

    if (bands > 0 && bands < b.lines) {
      failures.push(
        `  ${String(width).padStart(4)}px  ${b.tag.padEnd(4)} ${b.lines} lines -> ${bands} ink bands  "${b.text}"`,
      );
    }
  }
  await page.close();
}

console.log(
  failures.length === 0
    ? `PASS — every wrapped line renders as its own ink band across ${WIDTHS.length} widths, 320px to 2560px`
    : `FAIL — ${failures.length} blocks with merged lines`,
);
failures.slice(0, 30).forEach((f) => console.log(f));
await browser.close();
process.exit(failures.length === 0 ? 0 : 1);
