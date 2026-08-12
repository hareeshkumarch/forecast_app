import { chromium } from "@playwright/test";

const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

/*
 * The geometry unit tests prove the numbers at n = 8, 35 and 120. This proves
 * the render: a label's anchor can sit inside the frame while the glyphs it
 * anchors run outside it, and only the browser knows how wide a word is once
 * the mono face has loaded.
 */
const browser = await chromium.launch({ executablePath: CHROME });
const page = await browser.newPage({ viewport: { width: 1512, height: 950 } });
await page.goto("http://localhost:3000", { waitUntil: "networkidle" });
await page.waitForTimeout(400);

const measured = await page.evaluate(() => {
  const svg = document.querySelector('svg[role="img"]');
  const [vx, vy, vw, vh] = svg.getAttribute("viewBox").split(" ").map(Number);
  const escapes = [];
  for (const node of svg.querySelectorAll("polygon, line, text")) {
    const box = node.getBBox();
    if (
      box.x < vx - 0.5 ||
      box.y < vy - 0.5 ||
      box.x + box.width > vx + vw + 0.5 ||
      box.y + box.height > vy + vh + 0.5
    ) {
      escapes.push({
        tag: node.tagName,
        text: node.textContent?.trim().slice(0, 24) ?? "",
        box: [box.x, box.y, box.width, box.height].map((v) => Math.round(v)),
      });
    }
  }

  const texts = [...svg.querySelectorAll("text")];
  const boxes = texts.map((t) => t.getBBox());
  const collisions = [];
  for (let i = 0; i < boxes.length; i++)
    for (let j = i + 1; j < boxes.length; j++) {
      const a = boxes[i];
      const b = boxes[j];
      if (a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height)
        collisions.push(`${texts[i].textContent} / ${texts[j].textContent}`);
    }

  // A label is legible only if the bars are not drawn over it.
  const bars = [...svg.querySelectorAll("polygon")].map((p) => p.getBBox());
  const overBars = [];
  for (let i = 0; i < texts.length; i++) {
    const a = boxes[i];
    if (
      bars.some(
        (b) => a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height,
      )
    )
      overBars.push(texts[i].textContent.trim());
  }

  return {
    viewBox: [vx, vy, vw, vh],
    escapes,
    collisions,
    overBars,
    labels: texts.map((t, i) => ({
      text: t.textContent.trim(),
      x: Math.round(boxes[i].x),
      right: Math.round(boxes[i].x + boxes[i].width),
      y: Math.round(boxes[i].y),
    })),
    perCharAdvance:
      boxes.length && texts.length
        ? Math.max(...texts.map((t, i) => boxes[i].width / t.textContent.trim().length))
        : 0,
  };
});

console.log(`viewBox = [${measured.viewBox.join(" ")}]`);
measured.labels.forEach((l) => console.log(`  label "${l.text}"  x ${l.x}..${l.right}  y ${l.y}`));
console.log(`  widest per-character advance: ${measured.perCharAdvance.toFixed(2)}px`);
console.log(`  geometry escaping viewBox: ${measured.escapes.length}`);
measured.escapes.slice(0, 6).forEach((e) => console.log(`      ${e.tag} "${e.text}" ${e.box}`));
console.log(`  label-on-label collisions: ${measured.collisions.length} ${measured.collisions.join(", ")}`);
console.log(`  labels drawn over bars:    ${measured.overBars.length} ${measured.overBars.join(", ")}`);

const ok =
  measured.escapes.length === 0 && measured.collisions.length === 0 && measured.overBars.length === 0;
console.log(ok ? "PASS" : "FAIL");
await browser.close();
process.exit(ok ? 0 : 1);
