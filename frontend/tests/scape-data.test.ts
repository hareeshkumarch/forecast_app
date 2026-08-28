import { describe, expect, it } from "vitest";

import { LONGEST_ROW_NAME, buildScape, rangeLift } from "@/lib/demand-scape";
import {
  FUTURE_WEEKS,
  HISTORY_WEEKS,
  SERIES,
  columned,
  readoutFor,
  seriesDescription,
  valueAt,
} from "@/lib/scape-data";

const scape = buildScape(SERIES.layers, SERIES.growth);

describe("the demand the chart draws", () => {
  it("draws one example rather than a gallery of them", () => {
    expect(SERIES.layers.length).toBeGreaterThan(1);
    expect(new Set(SERIES.layers.map((layer) => layer.id)).size).toBe(SERIES.layers.length);
    expect(new Set(SERIES.layers.map((layer) => layer.label)).size).toBe(SERIES.layers.length);
  });

  it("runs every product line over the same weeks, so a week is one column", () => {
    expect(new Set(SERIES.layers.map((layer) => layer.history.length)).size).toBe(1);
    expect(new Set(SERIES.layers.map((layer) => layer.future.length)).size).toBe(1);
    expect(scape.steps).toBe(HISTORY_WEEKS + FUTURE_WEEKS);
    expect(scape.rows).toBe(SERIES.layers.length);
  });

  it("plots only real, positive demand", () => {
    for (const layer of SERIES.layers) {
      for (const value of [...layer.history, ...layer.future]) {
        expect(Number.isFinite(value)).toBe(true);
        expect(value).toBeGreaterThan(0);
      }
    }
  });

  it("gives each product line its own shape rather than one scaled twice", () => {
    const shapes = SERIES.layers.map((layer) => layer.history.join(","));
    expect(new Set(shapes).size).toBe(SERIES.layers.length);

    const ratios = SERIES.layers[0]!.history.map(
      (value, index) => value / SERIES.layers[1]!.history[index]!,
    );
    expect(new Set(ratios.map((ratio) => ratio.toFixed(3))).size).toBeGreaterThan(1);
  });

  it("keeps the near line the smaller one, so it never hides the row behind it", () => {
    const [front, behind] = SERIES.layers;
    if (!front || !behind) throw new Error("the chart is drawn two lines deep");
    for (let step = 0; step < HISTORY_WEEKS + FUTURE_WEEKS; step++) {
      expect(valueAt(front, step)).toBeLessThan(valueAt(behind, step));
    }
  });

  it("names every row inside the gutter reserved for the name", () => {
    for (const layer of SERIES.layers) {
      expect(layer.label.length).toBeLessThanOrEqual(LONGEST_ROW_NAME);
    }
    expect(scape.rowLabels.map((label) => label.text)).toEqual(
      SERIES.layers.map((layer) => layer.label),
    );
  });

  it("says what it is drawing for anyone who cannot see it", () => {
    const spoken = seriesDescription();
    for (const layer of SERIES.layers) expect(spoken).toContain(layer.label);
    expect(spoken).toContain(`${HISTORY_WEEKS} weeks`);
    expect(spoken).toContain(`${FUTURE_WEEKS}-week`);
  });
});

describe("the rows sharing one scale", () => {
  it("draws the same demand at the same height whichever row it is in", () => {
    const front = scape.prisms.find(
      (prism) => prism.tone === "history" && prism.row === 0 && prism.step === 0,
    );
    const behind = scape.prisms.find(
      (prism) => prism.tone === "history" && prism.row === 1 && prism.step === 0,
    );
    if (!front || !behind) throw new Error("both rows must be drawn");

    const [chilled, ambient] = SERIES.layers;
    if (!chilled || !ambient) throw new Error("the chart is drawn two lines deep");
    // Same units per pixel in both rows: the ratio of the heights is the ratio
    // of the demand, which is what makes the depth comparable by eye.
    expect(front.height / behind.height).toBeCloseTo(
      valueAt(chilled, 0) / valueAt(ambient, 0),
      6,
    );
  });
});

describe("the range the demand earns", () => {
  it("widens with every step out", () => {
    const lifts = [1, 2, 3, 4, 5].map((step) => rangeLift(step, SERIES.growth));
    expect(lifts).toEqual([...lifts].sort((a, b) => a - b));
    expect(new Set(lifts).size).toBe(lifts.length);
  });

  it("stays a claim about weekly grocery demand rather than a shrug", () => {
    // Doubling by the end of the horizon would be describing a business this
    // chart is not drawing.
    expect(rangeLift(FUTURE_WEEKS, SERIES.growth)).toBeLessThan(1.5);
    expect(rangeLift(1, SERIES.growth)).toBeGreaterThan(1);
  });

  it("never lets a shell sit below the forecast it wraps", () => {
    for (const shell of scape.prisms.filter((prism) => prism.tone === "range")) {
      const bar = scape.prisms.find(
        (prism) => prism.tone === "future" && prism.row === shell.row && prism.step === shell.step,
      );
      if (!bar) throw new Error("every shell must wrap a forecast bar");
      expect(shell.height).toBeGreaterThan(bar.height);
    }
  });
});

describe("what a week reads out as", () => {
  it("calls the past actual and the future a range", () => {
    expect(readoutFor(0).range).toBe("actual");
    expect(readoutFor(HISTORY_WEEKS).range).not.toBe("actual");
  });

  it("counts the past backwards from today and the future forwards", () => {
    expect(readoutFor(0).label).toBe(`${HISTORY_WEEKS} weeks ago`);
    expect(readoutFor(HISTORY_WEEKS - 1).label).toBe("1 weeks ago");
    expect(readoutFor(HISTORY_WEEKS).label).toBe("Week +1");
  });

  it("quotes the whole week, and the product lines that make it up", () => {
    for (let step = 0; step < HISTORY_WEEKS + FUTURE_WEEKS; step++) {
      const readout = readoutFor(step);
      const total = SERIES.layers.reduce((sum, layer) => sum + valueAt(layer, step), 0);
      expect(readout.point).toContain(`${total} units`);

      for (const layer of SERIES.layers) {
        expect(readout.split).toContain(`${layer.label} ${valueAt(layer, step)}`);
      }
    }
  });

  it("puts the forecast inside the range it quotes", () => {
    for (let index = 0; index < FUTURE_WEEKS; index++) {
      const readout = readoutFor(HISTORY_WEEKS + index);
      const [low, high] = readout.range.split(" to ").map(Number);
      const point = Number(readout.point.replace(" units", ""));
      expect(low).toBeLessThanOrEqual(point);
      expect(high).toBeGreaterThanOrEqual(point);
    }
  });

  it("lays every forecast week on the same columns", () => {
    const lines = new Set<number>();
    const splits = new Set<number>();
    for (let index = 0; index < FUTURE_WEEKS; index++) {
      const readout = columned(readoutFor(HISTORY_WEEKS + index));
      lines.add(`${readout.label} · ${readout.point} · range ${readout.range}`.length);
      splits.add(readout.split.length);
    }
    expect(lines.size).toBe(1);
    expect(splits.size).toBe(1);
  });

  it("leaves the spoken readout unpadded", () => {
    const raw = readoutFor(HISTORY_WEEKS);
    expect(raw.point).toBe(raw.point.trim());
    expect(raw.range).toBe(raw.range.trim());
    expect(raw.split).toBe(raw.split.trim());
  });
});
