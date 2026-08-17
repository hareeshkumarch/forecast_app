import { chromium } from "@playwright/test";

/*
 * Whether the landing page is actually themed, or only mostly themed.
 *
 * The failure this exists for is not a page that stayed light — that is
 * obvious in a screenshot. It is one element out of eighty keeping a literal
 * colour while everything around it moves: a card still on drafting paper in
 * the dark theme, a caption still at 40% grey on a near-black ground. Both
 * read as a rendering fault rather than a design decision, and neither shows
 * up in a diff.
 *
 * So this walks every element the landing page draws, in both themes, and
 * asks two things of each: is the ink you paint actually visible against the
 * ground behind you, and — in the dark theme — is that ground dark at all.
 * The contrast is computed the way WCAG defines it, against the first opaque
 * ancestor, because a colour is only legible with respect to what is under it.
 */

const BASE = process.env.BASE ?? "http://localhost:3000";
const CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome";

const browser = await chromium.launch({ executablePath: CHROME });
const fail = [];
const line = (s) => console.log(s);

/** Text this size and weight is "large" to WCAG, and passes at 3:1. */
const LARGE_PX = 24;

/*
 * How big an opaque fill has to be before "it is still light in the dark
 * theme" means anything.
 *
 * Plenty of small fills are meant to stay light in both themes and are not
 * bugs: every swatch in a chart key, the accent behind a rule, and the call to
 * action, which is the darkest thing on a light page precisely so it can be
 * the lightest thing on a dark one. What cannot stay light is a *ground* — a
 * card, a panel, a section — because that is the element that was supposed to
 * move and did not. The largest of those exceptions is a button at roughly
 * 260x52; the smallest card on the page is about 390x190. Anything at or over
 * this is a ground.
 */
const GROUND_AREA = 40_000;

const survey = async (theme) => {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    colorScheme: theme,
  });
  await page.goto(BASE, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  // Every section revealed and every animation landed: an element measured
  // mid-reveal is at opacity 0 and reports contrast it does not have.
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

      /* What is actually behind an element: its own background composited
         over its ancestors', down to the first opaque one. A caption with no
         background of its own is sitting on whatever its card is sitting on. */
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

        // Only elements that actually hold text of their own.
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
    // A ground still lighter than mid-grey in the dark theme is an element
    // that kept its literal colour while the page around it moved.
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
