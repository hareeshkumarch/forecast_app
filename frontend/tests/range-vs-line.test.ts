import { describe, expect, it } from "vitest";

import { area, buildPanel, path, spreadAt } from "@/lib/range-vs-line";

const line = buildPanel(false);
const ranged = buildPanel(true);

describe("the comparison the section is making", () => {
  it("puts the outcome inside the range and away from the line", () => {
    expect(ranged.outcome.insideBand).toBe(true);
    expect(ranged.outcome.onLine).toBe(false);
  });

  it("leaves the outcome visibly inside the band rather than sitting on its edge", () => {
    const band = ranged.band;
    if (!band) throw new Error("the ranged panel must have a band");

    const upper = band.upper.at(-1);
    const lower = band.lower.at(-1);
    if (!upper || !lower) throw new Error("the band must reach the end of the horizon");

    const depth = lower.y - upper.y;
    expect(ranged.outcome.y - upper.y).toBeGreaterThan(depth * 0.15);
    expect(lower.y - ranged.outcome.y).toBeGreaterThan(depth * 0.15);
  });

  it("puts the outcome far enough below the line to read as a miss", () => {
    const predicted = ranged.projection.at(-1);
    if (!predicted) throw new Error("the panel must plot a projection");

    expect(ranged.outcome.y - predicted.y).toBeGreaterThan(12);
  });

  it("draws no band on the line-only panel", () => {
    expect(line.band).toBeNull();
    expect(ranged.band).not.toBeNull();
  });

  it("plots the same history and the same projection in both panels", () => {
    expect(line.history).toEqual(ranged.history);
    expect(line.projection).toEqual(ranged.projection);
    expect(line.outcome.x).toBeCloseTo(ranged.outcome.x);
    expect(line.outcome.y).toBeCloseTo(ranged.outcome.y);
  });
});

describe("the geometry stays inside its box", () => {
  it("keeps every drawn point within the viewBox", () => {
    const points = [
      ...ranged.history,
      ...ranged.projection,
      ...(ranged.band?.upper ?? []),
      ...(ranged.band?.lower ?? []),
      { x: ranged.outcome.x, y: ranged.outcome.y },
    ];

    for (const point of points) {
      expect(point.x).toBeGreaterThanOrEqual(0);
      expect(point.x).toBeLessThanOrEqual(ranged.width);
      expect(point.y).toBeGreaterThanOrEqual(0);
      expect(point.y).toBeLessThanOrEqual(ranged.height);
    }
  });

  it("advances left to right without doubling back", () => {
    const xs = ranged.history.map((point) => point.x);
    expect(xs).toEqual([...xs].sort((a, b) => a - b));
    expect(new Set(xs).size).toBe(xs.length);
  });

  it("hands the forecast off from the last point of history", () => {
    const last = ranged.history.at(-1);
    if (!last) throw new Error("the panel must plot some history");

    expect(ranged.projection[0]).toEqual(last);
    expect(ranged.split).toBeCloseTo(last.x);
  });
});

describe("the range behaves like a range", () => {
  it("widens with every step out", () => {
    const widths = [1, 2, 3, 4].map((step) => spreadAt(step));
    expect(widths).toEqual([...widths].sort((a, b) => a - b));
    expect(new Set(widths).size).toBe(widths.length);
  });

  it("opens from a single point rather than starting already wide", () => {
    const band = ranged.band;
    if (!band) throw new Error("the ranged panel must have a band");

    expect(band.upper[0]).toEqual(band.lower[0]);

    const widest = band.upper.at(-1);
    const floor = band.lower.at(-1);
    if (!widest || !floor) throw new Error("the band must reach the end of the horizon");
    expect(floor.y - widest.y).toBeGreaterThan(20);
  });

  it("never inverts, so the upper edge is always above the lower", () => {
    const band = ranged.band;
    if (!band) throw new Error("the ranged panel must have a band");

    for (const [index, upper] of band.upper.entries()) {
      const lower = band.lower[index];
      if (!lower) throw new Error("both edges must have the same number of points");
      expect(upper.y).toBeLessThanOrEqual(lower.y);
    }
  });
});

describe("the svg strings it produces", () => {
  it("writes a path that starts with a move and only draws lines", () => {
    const drawn = path(ranged.projection);
    expect(drawn.startsWith("M")).toBe(true);
    expect(drawn.match(/M/g)).toHaveLength(1);
    expect(drawn).not.toContain("NaN");
  });

  it("closes the band so it can be filled", () => {
    const band = ranged.band;
    if (!band) throw new Error("the ranged panel must have a band");

    const drawn = area(band);
    expect(drawn.startsWith("M")).toBe(true);
    expect(drawn.endsWith("Z")).toBe(true);
    expect(drawn).not.toContain("NaN");
  });
});
