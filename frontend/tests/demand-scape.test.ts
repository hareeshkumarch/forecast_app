import { describe, expect, it } from "vitest";

import { buildScape, labelWidth, prismFaces, scapeVertices, projectPoint, type Layer } from "@/lib/demand-scape";

function required<T>(value: T | undefined, what: string): T {
  if (value === undefined) throw new Error(`missing ${what}`);
  return value;
}

const series = (count: number, seed: number) =>
  Array.from({ length: count }, (_, index) => 40 + ((index * seed) % 80));

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

  it("adds bars without moving the frame", () => {
    const boxes = LENGTHS.map((n) => buildScape(layers(n - 9, 9)).viewBox);
    expect(new Set(boxes).size).toBe(1);
  });

  it.each(LENGTHS)("keeps whole captions, not just their anchors, off the bars at n = %i", (n) => {
    const scape = buildScape(layers(n - 9, 9));
    const box = parseViewBox(scape.viewBox);
    const plotLeft = Math.min(...scapeVertices(scape).map(([x]) => x));
    const plotRight = Math.max(...scapeVertices(scape).map(([x]) => x));

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
    const xs = scapeVertices(scape).map(([x]) => x);
    const plotLeft = Math.min(...xs);
    const plotRight = Math.max(...scapeVertices(scape).map(([x]) => x));
    const plotBottom = Math.max(...scapeVertices(scape).map(([, y]) => y));

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
    const plotLeft = Math.min(...scapeVertices(scape).map(([x]) => x));

    expect(scape.rowLabels.map((label) => label.text)).toEqual(["Front", "Behind"]);
    for (const label of scape.rowLabels) {
      expect(label.x).toBeLessThanOrEqual(plotLeft);
      expect(label.x - labelWidth(label.text)).toBeGreaterThanOrEqual(
        parseViewBox(scape.viewBox).x,
      );
    }

    const [front, behind] = scape.rowLabels;
    expect(required(front, "front name").y).toBeGreaterThan(required(behind, "back name").y);

  });

  it("keeps the oldest-week caption clear of the row names", () => {
    const scape = buildScape(layers(26, 9));
    const past = required(
      scape.labels.find((label) => label.key === "past"),
      "past caption",
    );

    for (const label of scape.rowLabels) {
      expect(past.y).toBeLessThan(label.y);
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
  it("makes equal volumes smaller as they recede from the camera", () => {
    const projectedHeight = (z: number) =>
      projectPoint({ x: 0, y: 0, z }).y - projectPoint({ x: 0, y: 100, z }).y;
    expect(projectedHeight(300)).toBeLessThan(projectedHeight(0) * 0.9);
    const projectedWidth = (z: number) =>
      projectPoint({ x: 40, y: 0, z }).x - projectPoint({ x: 0, y: 0, z }).x;
    expect(projectedWidth(300)).toBeLessThan(projectedWidth(0));
  });

  it("paints farther volumes first so near columns occlude them", () => {
    const scape = buildScape(layers(16, 8));
    for (let index = 1; index < scape.prisms.length; index++) {
      expect(scape.prisms[index]!.cameraDepth).toBeLessThanOrEqual(scape.prisms[index - 1]!.cameraDepth);
    }
  });

  it("keeps contact and cast shadows on the ground and inside the frame", () => {
    const scape = buildScape(layers(16, 8));
    const box = parseViewBox(scape.viewBox);
    for (const prism of scape.prisms) {
      const faces = prismFaces(prism);
      expect(faces.shadow).not.toBe(faces.floor);
      for (const point of `${faces.shadow} ${faces.floor}`.split(" ")) {
        const [x = 0, y = 0] = point.split(",").map(Number);
        expect(x).toBeGreaterThan(box.x);
        expect(x).toBeLessThan(box.x + box.width);
        expect(y).toBeGreaterThan(box.y);
        expect(y).toBeLessThan(box.y + box.height);
      }
    }
  });

  it("has finite geometry for empty input", () => {
    const scape = buildScape([]);
    expect(scape.prisms).toHaveLength(0);
    expect(scape.viewBox.split(" ").map(Number).every(Number.isFinite)).toBe(true);
  });

});
