import { chromium } from "@playwright/test";

const BASE = process.env.BASE ?? "http://localhost:3000";
const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

const browser = await chromium.launch({ executablePath: CHROME });
const fail = [];
const line = (s) => console.log(s);

const LARGE_PX = 24;

const GROUND_AREA = 40_000;

const survey = async (theme) => {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    colorScheme: theme,
  });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(async () => {
    for (const section of document.querySelectorAll("section, footer")) {
      section.scrollIntoView();
      await new Promise((r) => setTimeout(r, 220));
    }
    window.scrollTo(0, 0);
  });
  await page.waitForTimeout(1200);

  const result = await page.evaluate(
    ({ largePx, groundArea }) => {
      const parse = (value) => {
        const parts = value.match(/[\d.]+/g)?.map(Number) ?? [];
        if (parts.length < 3) return null;
        return { r: parts[0], g: parts[1], b: parts[2], a: parts.length > 3 ? parts[3] : 1 };
      };

      const over = (top, bottom) => ({
        r: top.r * top.a + bottom.r * (1 - top.a),
        g: top.g * top.a + bottom.g * (1 - top.a),
        b: top.b * top.a + bottom.b * (1 - top.a),
        a: 1,
      });

      const luminance = ({ r, g, b }) => {
        const channel = (value) => {
          const v = value / 255;
          return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
        };
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
      };

      const contrast = (a, b) => {
        const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
        return (hi + 0.05) / (lo + 0.05);
      };

      const groundOf = (node) => {
        let ground = { r: 255, g: 255, b: 255, a: 1 };
        const stack = [];
        for (let el = node; el; el = el.parentElement) {
          const fill = parse(getComputedStyle(el).backgroundColor);
          if (!fill || fill.a === 0) continue;
          stack.push(fill);
          if (fill.a === 1) break;
        }
        for (const fill of stack.reverse()) ground = over(fill, ground);
        return ground;
      };

      const root = document.querySelector(".forecast-landing");
      const readable = [];
      const grounds = new Map();

      for (const el of root.querySelectorAll("*")) {
        const style = getComputedStyle(el);
        if (style.visibility === "hidden" || style.display === "none") continue;
        if (Number(style.opacity) < 0.6) continue;

        const box = el.getBoundingClientRect();
        if (box.width < 2 || box.height < 2) continue;

        const own = parse(style.backgroundColor);
        if (own && own.a === 1 && box.width * box.height >= groundArea) {
          grounds.set(style.backgroundColor, (grounds.get(style.backgroundColor) ?? 0) + 1);
        }

        const text = [...el.childNodes]
          .filter((child) => child.nodeType === 3)
          .map((child) => child.textContent.trim())
          .join("");
        if (!text) continue;

        const ink = parse(style.color);
        if (!ink || ink.a === 0) continue;

        const ground = groundOf(el);
        const ratio = contrast(over(ink, ground), ground);
        const size = parseFloat(style.fontSize);
        const large = size >= largePx || (size >= 18.66 && Number(style.fontWeight) >= 700);

        readable.push({
          ratio: Math.round(ratio * 100) / 100,
          floor: large ? 3 : 4.5,
          text: text.slice(0, 42),
          tag: el.tagName.toLowerCase(),
          color: style.color,
          on: `rgb(${Math.round(ground.r)}, ${Math.round(ground.g)}, ${Math.round(ground.b)})`,
        });
      }

      return {
        canvas: getComputedStyle(root).backgroundColor,
        theme: document.documentElement.dataset.theme,
        grounds: [...grounds.keys()],
        readable,
        checked: readable.length,
      };
    },
    { largePx: LARGE_PX, groundArea: GROUND_AREA },
  );

  await page.close();
  return result;
};

for (const theme of ["light", "dark"]) {
  line(`\n${theme} — every element on the ground it is actually drawn on`);
  const seen = await survey(theme);

  line(`  theme "${seen.theme}" · canvas ${seen.canvas} · ${seen.checked} text elements`);

  if (seen.theme !== theme) fail.push(`${theme}: the document resolved to "${seen.theme}"`);

  const thin = seen.readable.filter((item) => item.ratio < item.floor);
  for (const item of thin) {
    fail.push(
      `${theme}: ${item.ratio}:1 (needs ${item.floor}) — <${item.tag}> "${item.text}" ${item.color} on ${item.on}`,
    );
  }
  const worst = [...seen.readable].sort((a, b) => a.ratio - b.ratio).slice(0, 3);
  line(`  thinnest contrast: ${worst.map((i) => `${i.ratio}:1 "${i.text}"`).join(" · ")}`);
  line(`  under the floor: ${thin.length === 0 ? "none  ok" : `${thin.length}  FAIL`}`);

  if (theme === "dark") {
    const light = seen.grounds.filter((fill) => {
      const [r, g, b] = fill.match(/\d+/g).map(Number);
      return (r + g + b) / 3 > 128;
    });
    if (light.length) fail.push(`dark: ${light.length} surfaces stayed light: ${light.join(", ")}`);
    line(`  grounds: ${seen.grounds.join(", ")}`);
    line(`  none left on paper: ${light.length === 0 ? "ok" : "FAIL"}`);
  }
}

await browser.close();

line("");
if (fail.length) {
  line(`THEME GATE: ${fail.length} FAILURES`);
  for (const item of fail) line(`  ${item}`);
  process.exit(1);
}
line("all checks passed");
