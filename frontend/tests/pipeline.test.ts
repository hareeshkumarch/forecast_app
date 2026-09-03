import { describe, expect, it } from "vitest";

import {
  AHEAD,
  COLUMNS,
  ROWS,
  SLOTS,
  SOLD,
  STAGE,
  activeStep,
  beats,
  columnX,
  lift,
  morph,
  rowY,
  slotX,
  spread,
} from "@/lib/pipeline";

describe("the sheet", () => {
  it("names exactly one date column and one quantity column", () => {
    expect(COLUMNS.filter((column) => column.role === "date")).toHaveLength(1);
    expect(COLUMNS.filter((column) => column.role === "value")).toHaveLength(1);
  });

  it("leaves columns for the second beat to pass over", () => {
    expect(COLUMNS.filter((column) => !column.role).length).toBeGreaterThanOrEqual(1);
  });

  it("fills the drawing exactly, so no column hangs off the frame", () => {
    expect(columnX(COLUMNS.length)).toBe(STAGE.width);
  });

  it("holds real consecutive weeks", () => {
    expect(ROWS).toHaveLength(SOLD.length);
    const days = ROWS.map((row) => Date.parse(`${row.week}T00:00:00Z`));
    expect(days.every((day) => Number.isFinite(day))).toBe(true);
    for (let index = 1; index < days.length; index += 1) {
      expect(days[index]! - days[index - 1]!).toBe(7 * 86_400_000);
    }
  });

  it("keeps the sheet clear of the baseline the bars land on", () => {
    expect(rowY(ROWS.length - 1) + STAGE.cellHeight).toBeLessThan(STAGE.baseline);
  });
});

describe("the morph", () => {
  it("lands every cell on its own slot, at the baseline", () => {
    const column = COLUMNS.findIndex((entry) => entry.role === "value");
    SOLD.forEach((_, index) => {
      const shape = morph(index);
      expect(columnX(column) + shape.dx).toBeCloseTo(slotX(index), 5);
      expect(rowY(index) + STAGE.cellHeight + shape.dy).toBeCloseTo(STAGE.baseline, 5);
    });
  });

  it("narrows the cell to a bar and grows it to its value", () => {
    const width = COLUMNS.find((entry) => entry.role === "value")?.width ?? 0;
    SOLD.forEach((value, index) => {
      const shape = morph(index);
      expect(width * shape.sx).toBeCloseTo(STAGE.barWidth, 5);
      expect(STAGE.cellHeight * shape.sy).toBeCloseTo(lift(value), 5);
    });
  });

  it("leaves the bars clear of each other once they have arrived", () => {
    for (let index = 1; index < SOLD.length; index += 1) {
      expect(slotX(index) - slotX(index - 1)).toBeGreaterThan(STAGE.barWidth);
    }
  });
});

describe("the chart", () => {
  it("draws history and forecast on one scale, inside the frame", () => {
    expect(SLOTS).toBe(SOLD.length + AHEAD.length);
    const tallest = Math.max(
      ...SOLD.map(lift),
      ...AHEAD.map((value, step) => lift(value * (1 + spread(step)))),
    );
    expect(tallest).toBeLessThanOrEqual(STAGE.ceiling + 0.001);
    expect(STAGE.baseline - tallest).toBeGreaterThan(0);
  });

  it("opens the range as the horizon lengthens, never before it", () => {
    const widths = AHEAD.map((_, step) => spread(step));
    expect(widths[0]).toBeGreaterThan(0);
    for (let step = 1; step < widths.length; step += 1) {
      expect(widths[step]).toBeGreaterThan(widths[step - 1]!);
    }
  });

  it("keeps the last slot inside the drawing", () => {
    expect(slotX(SLOTS - 1) + STAGE.barWidth).toBeLessThanOrEqual(STAGE.width);
  });
});

describe("the scrub", () => {
  it("starts at nothing and settles before the pin lets go", () => {
    expect(beats(0)).toEqual({ fill: 0, read: 0, build: 0, ahead: 0 });
    const settled = beats(0.87);
    expect(settled.fill).toBe(1);
    expect(settled.read).toBe(1);
    expect(settled.build).toBe(1);
    expect(settled.ahead).toBe(1);
  });

  it("never runs a beat backwards", () => {
    let previous = beats(0);
    for (let tick = 1; tick <= 100; tick += 1) {
      const current = beats(tick / 100);
      expect(current.fill).toBeGreaterThanOrEqual(previous.fill);
      expect(current.read).toBeGreaterThanOrEqual(previous.read);
      expect(current.build).toBeGreaterThanOrEqual(previous.build);
      expect(current.ahead).toBeGreaterThanOrEqual(previous.ahead);
      previous = current;
    }
  });

  it("holds every beat inside nought to one, past both ends", () => {
    for (const progress of [-2, -0.1, 0, 0.5, 1, 1.4]) {
      for (const value of Object.values(beats(progress))) {
        expect(value).toBeGreaterThanOrEqual(0);
        expect(value).toBeLessThanOrEqual(1);
      }
    }
  });

  it("finishes one beat before the next has anything to show", () => {
    // The read cannot start on a sheet that is still landing, and the build
    // cannot start on columns that have not been picked out.
    for (let tick = 0; tick <= 100; tick += 1) {
      const { fill, read, build } = beats(tick / 100);
      if (read > 0) expect(fill).toBe(1);
      if (build > 0) expect(read).toBe(1);
    }
  });

  it("lights the step whose beat is running", () => {
    expect(activeStep(0)).toBe(0);
    expect(activeStep(0.4)).toBe(1);
    expect(activeStep(1)).toBe(2);
    // Every step is reached, or one of the three is never readable.
    const seen = new Set(Array.from({ length: 101 }, (_, tick) => activeStep(tick / 100)));
    expect([...seen].sort()).toEqual([0, 1, 2]);
  });
});
