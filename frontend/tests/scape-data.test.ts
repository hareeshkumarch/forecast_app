import { describe, expect, it } from "vitest";

import { buildScape, rangeLift } from "@/lib/demand-scape";
import { SCENARIOS, columned, readoutFor, scenarioById } from "@/lib/scape-data";

const scapes = SCENARIOS.map((scenario) =>
  buildScape(scenario.history, scenario.future, scenario.growth),
);

describe("the shapes the chart can be asked to draw", () => {
  it("offers more than one, and names them all differently", () => {
    expect(SCENARIOS.length).toBeGreaterThan(1);
    expect(new Set(SCENARIOS.map((s) => s.id)).size).toBe(SCENARIOS.length);
    expect(new Set(SCENARIOS.map((s) => s.label)).size).toBe(SCENARIOS.length);
  });

  it("runs every series over the same weeks, so swapping cannot resize the chart", () => {
    expect(new Set(SCENARIOS.map((s) => s.history.length)).size).toBe(1);
    expect(new Set(SCENARIOS.map((s) => s.future.length)).size).toBe(1);
    expect(new Set(scapes.map((scape) => scape.viewBox)).size).toBe(1);
  });

  it("plots only real, positive demand", () => {
    for (const scenario of SCENARIOS) {
      for (const value of [...scenario.history, ...scenario.future]) {
        expect(Number.isFinite(value)).toBe(true);
        expect(value).toBeGreaterThan(0);
      }
    }
  });

  it("actually draws different shapes rather than the same one relabelled", () => {
    const shapes = SCENARIOS.map((s) => s.history.join(","));
    expect(new Set(shapes).size).toBe(SCENARIOS.length);
  });

  it("hands back the default rather than nothing when asked for a series it has not got", () => {
    expect(scenarioById("no-such-series")).toBe(SCENARIOS[0]);
    for (const scenario of SCENARIOS) {
      expect(scenarioById(scenario.id)).toBe(scenario);
    }
  });
});

describe("the range each shape earns", () => {
  it("opens at a different rate for each, so the width means something", () => {
    expect(new Set(SCENARIOS.map((s) => s.growth)).size).toBe(SCENARIOS.length);
  });

  it("widens with every step out, whatever the rate", () => {
    for (const scenario of SCENARIOS) {
      const lifts = [1, 2, 3, 4, 5].map((step) => rangeLift(step, scenario.growth));
      expect(lifts).toEqual([...lifts].sort((a, b) => a - b));
      expect(new Set(lifts).size).toBe(lifts.length);
    }
  });

  it("gives the season that turns a wider range than the launch that settles", () => {
    const fashion = SCENARIOS.find((s) => s.id === "fashion");
    const electronics = SCENARIOS.find((s) => s.id === "electronics");
    if (!fashion || !electronics) throw new Error("both shapes must exist");
    expect(rangeLift(9, fashion.growth)).toBeGreaterThan(rangeLift(9, electronics.growth));
  });

  it("never lets a shell sit below the forecast it wraps", () => {
    for (const scape of scapes) {
      for (const shell of scape.prisms.filter((prism) => prism.tone === "range")) {
        const bar = scape.prisms.find(
          (prism) => prism.tone === "future" && prism.row === shell.row && prism.step === shell.step,
        );
        if (!bar) throw new Error("every shell must wrap a forecast bar");
        expect(shell.height).toBeGreaterThan(bar.height);
      }
    }
  });
});

describe("what a week reads out as", () => {
  it("calls the past actual and the future a range", () => {
    for (const scenario of SCENARIOS) {
      expect(readoutFor(scenario, 0).range).toBe("actual");
      expect(readoutFor(scenario, scenario.history.length).range).not.toBe("actual");
    }
  });

  it("counts the past backwards from today and the future forwards", () => {
    for (const scenario of SCENARIOS) {
      const last = scenario.history.length - 1;
      expect(readoutFor(scenario, 0).label).toBe(`${scenario.history.length} weeks ago`);
      expect(readoutFor(scenario, last).label).toBe("1 weeks ago");
      expect(readoutFor(scenario, scenario.history.length).label).toBe("Week +1");
    }
  });

  it("puts the forecast inside the range it quotes", () => {
    for (const scenario of SCENARIOS) {
      for (let index = 0; index < scenario.future.length; index++) {
        const readout = readoutFor(scenario, scenario.history.length + index);
        const [low, high] = readout.range.split(" to ").map(Number);
        const point = Number(readout.point.replace(" units", ""));
        expect(low).toBeLessThanOrEqual(point);
        expect(high).toBeGreaterThanOrEqual(point);
      }
    }
  });

  it("lays every forecast week on the same columns, in every scenario", () => {
    const widths = new Set<number>();
    for (const scenario of SCENARIOS) {
      for (let index = 0; index < scenario.future.length; index++) {
        const readout = columned(readoutFor(scenario, scenario.history.length + index));
        widths.add(`${readout.label} · ${readout.point} · range ${readout.range}`.length);
      }
    }
    expect(widths.size).toBe(1);
  });

  it("leaves the spoken readout unpadded", () => {
    const scenario = SCENARIOS[0];
    if (!scenario) throw new Error("there must be a scenario");
    const raw = readoutFor(scenario, scenario.history.length);
    expect(raw.point).toBe(raw.point.trim());
    expect(raw.range).toBe(raw.range.trim());
  });
});
