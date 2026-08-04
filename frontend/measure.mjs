import { chromium } from "@playwright/test";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1600, height: 960 } });
await p.goto("http://localhost:3000", { waitUntil: "networkidle" });
await p.waitForTimeout(2500);
const m = await p.evaluate(() => {
  const q = (s) => document.querySelector(s);
  const box = (el) => el ? { h: Math.round(el.getBoundingClientRect().height), w: Math.round(el.getBoundingClientRect().width), top: Math.round(el.getBoundingClientRect().top), bottom: Math.round(el.getBoundingClientRect().bottom) } : null;
  const main = q("main");
  const cards = [...document.querySelectorAll("main .card")].map(c => box(c));
  return {
    header: box(q("header")),
    leftRail: box(q('aside[aria-label="Data connectors"]')),
    rightRail: box(q('aside[aria-label="AI insights"]')),
    main: box(main),
    mainScrollH: main?.scrollHeight,
    mainClientH: main?.clientHeight,
    overflow: (main?.scrollHeight ?? 0) - (main?.clientHeight ?? 0),
    cards,
  };
});
console.log(JSON.stringify(m, null, 1));
await b.close();
