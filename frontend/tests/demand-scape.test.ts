import { describe, expect, it } from "vitest";

import { buildScape, labelWidth, prismFaces, scapeVertices, type Layer } from "@/lib/demand-scape";

function required<T>(value: T | undefined, what: string): T {
  if (value === undefined) throw new Error(`missing ${what}`);
  return value;
}

const series = (count: number, seed: number) =>
  Array.from({ length: count }, (_, index) => 40 + ((index * seed) % 80));

/** Two rows of made-up demand, the shape the chart is always handed. */
const layers = (historyCount: number, futureCount: number): Layer[] => [
  {
    id: "front",
    label: "Front",
    history: series(historyCount, 7).map((value) => value * 0.6),
    future: series(futureCount, 5).map((value) => value * 0.6),
  },
  {
    id: "behind",
    label: "Behind",
    history: series(historyCount, 7),
    future: series(futureCount, 5),
  },
];

const parseViewBox = (viewBox: string) => {
  const parts = viewBox.split(" ").map(Number);
  return {
    x: required(parts[0], "viewBox x"),
    y: required(parts[1], "viewBox y"),
    width: required(parts[2], "viewBox width"),
    height: required(parts[3], "viewBox height"),
  };
};

const LENGTHS = [8, 35, 120];

describe("demand scape geometry", () => {
  it.each(LENGTHS)("keeps every vertex inside the viewBox at n = %i", (n) => {
    const historyLength = Math.max(1, n - Math.min(9, Math.floor(n / 2)));
    const scape = buildScape(layers(historyLength, n - historyLength));
    const box = parseViewBox(scape.viewBox);

    for (const [x, y] of scapeVertices(scape)) {
      expect(x).toBeGreaterThanOrEqual(box.x);
      expect(x).toBeLessThanOrEqual(box.x + box.width);
      expect(y).toBeGreaterThanOrEqual(box.y);
      expect(y).toBeLessThanOrEqual(box.y + box.height);
    }
  });

  it.each(LENGTHS)("keeps guides and labels inside the viewBox at n = %i", (n) => {
    const scape = buildScape(layers(n - 9, 9));
    const box = parseViewBox(scape.viewBox);
    const within = (x: number, y: number) =>
      x >= box.x && x <= box.x + box.width && y >= box.y && y <= box.y + box.height;

    for (const guide of scape.guides) {
      expect(within(guide.x1, guide.y1)).toBe(true);
      expect(within(guide.x2, guide.y2)).toBe(true);
    }
    for (const label of [...scape.labels, ...scape.rowLabels]) {
      expect(within(label.x, label.y)).toBe(true);
    }
    expect(within(scape.boundary.x1, scape.boundary.y1)).toBe(true);
    expect(within(scape.boundary.x2, scape.boundary.y2)).toBe(true);
  });

  it("holds its aspect ratio steady as the series grows", () => {
    const ratios = LENGTHS.map((n) => {
      const scape = buildScape(layers(n - 9, 9));
      return scape.width / scape.height;
    });

    const baseline = required(ratios[0], "baseline ratio");
    for (const ratio of ratios) {
      expect(ratio / baseline).toBeGreaterThan(0.98);
      expect(ratio / baseline).toBeLessThan(1.02);
    }
  });

  it("spends a fixed drift budget however many bars divide it", () => {
    const drift = LENGTHS.map((n) => {
      const scape = buildScape(layers(n - 9, 9));
      const front = scape.prisms.filter((prism) => prism.row === 0);
      const first = required(front[0], "first prism");
      const last = required(front[front.length - 1], "last prism");
      return {
        down: last.baseY - first.baseY,
        across: last.x + last.width + last.extrudeX - first.x,
      };
    });

    const baseline = required(drift[0], "baseline drift");
    for (const step of drift) {
      expect(step.down).toBeCloseTo(baseline.down, 6);
      expect(step.across).toBeCloseTo(baseline.across, 6);
    }
  });

  it("walks no further at 120 bars than at 8", () => {
    const reach = LENGTHS.map((n) => {
      const scape = buildScape(layers(n - 9, 9));
      const xs = scapeVertices(scape).map(([x]) => x);
      return Math.max(...xs);
    });
    const baseline = required(reach[0], "baseline reach");
    for (const far of reach) expect(far).toBeCloseTo(baseline, 6);
  });

  it("adds bars without moving the frame", () => {
    const boxes = LENGTHS.map((n) => buildScape(layers(n - 9, 9)).viewBox);
    expect(new Set(boxes).size).toBe(1);
  });

  it.each(LENGTHS)("keeps whole captions, not just their anchors, off the bars at n = %i", (n) => {
    const scape = buildScape(layers(n - 9, 9));
    const box = parseViewBox(scape.viewBox);
    const plotLeft = Math.min(...scape.prisms.map((prism) => prism.x));
    const plotRight = Math.max(...scape.prisms.map((p) => p.x + p.width + p.extrudeX));

    for (const label of scape.labels) {
      const width = labelWidth(label.text);
      const start =
        label.anchor === "start" ? label.x : label.anchor === "end" ? label.x - width : label.x - width / 2;
      const end = start + width;

      expect(start).toBeGreaterThanOrEqual(box.x);
      expect(end).toBeLessThanOrEqual(box.x + box.width);

      if (label.key === "past") expect(end).toBeLessThan(plotLeft);
      if (label.key === "horizon") expect(start).toBeGreaterThan(plotRight);
    }
  });

  it("keeps labels out of the band the bars occupy", () => {
    const scape = buildScape(layers(26, 9));
    const xs = scape.prisms.map((prism) => prism.x);
    const plotLeft = Math.min(...xs);
    const plotRight = Math.max(...scape.prisms.map((p) => p.x + p.width + p.extrudeX));
    const plotBottom = Math.max(...scape.prisms.map((prism) => prism.baseY));

    const past = scape.labels.find((label) => label.key === "past");
    const today = scape.labels.find((label) => label.key === "today");
    const horizon = scape.labels.find((label) => label.key === "horizon");

    expect(past?.x).toBeLessThan(plotLeft);
    expect(today?.y).toBeGreaterThan(plotBottom);
    expect(horizon?.x).toBeGreaterThan(plotRight);
  });

  it("names the series length it was given", () => {
    const scape = buildScape(layers(26, 9));
    expect(scape.labels.map((label) => label.text)).toEqual([
      "26 weeks ago",
      "today",
      "+9 weeks",
    ]);
  });

  it("names each row where that row begins, in the gutter beside it", () => {
    const scape = buildScape(layers(26, 9));
    const plotLeft = Math.min(...scape.prisms.map((prism) => prism.x));

    expect(scape.rowLabels.map((label) => label.text)).toEqual(["Front", "Behind"]);
    for (const label of scape.rowLabels) {
      expect(label.x).toBeLessThanOrEqual(plotLeft);
      expect(label.x - labelWidth(label.text)).toBeGreaterThanOrEqual(
        parseViewBox(scape.viewBox).x,
      );
    }

    // Each name sits on its own row's baseline, so the two are as far apart
    // vertically as the rows they belong to.
    const [front, behind] = scape.rowLabels;
    const baselines = scape.prisms.filter((prism) => prism.step === 0);
    const rowGap =
      required(
        baselines.find((prism) => prism.row === 0),
        "front row",
      ).baseY -
      required(
        baselines.find((prism) => prism.row === 1),
        "back row",
      ).baseY;
    expect(required(front, "front name").y - required(behind, "back name").y).toBeCloseTo(
      rowGap,
      6,
    );
  });

  it("keeps the oldest-week caption clear of the row names", () => {
    const scape = buildScape(layers(26, 9));
    const past = required(
      scape.labels.find((label) => label.key === "past"),
      "past caption",
    );

    for (const label of scape.rowLabels) {
      expect(past.y).toBeLessThan(label.y);
      // A mono line at font-size 15: anything closer would have the two sets
      // of glyphs touching.
      expect(label.y - past.y).toBeGreaterThan(15);
    }
  });

  it("draws a bar as three closed faces", () => {
    const scape = buildScape(layers(26, 9));
    const faces = prismFaces(required(scape.prisms[0], "first prism"));
    for (const face of [faces.front, faces.side, faces.top]) {
      expect(face.split(" ")).toHaveLength(4);
    }
  });
});
