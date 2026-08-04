import { describe, expect, it } from "vitest";

import { formatDateRange } from "@/lib/format";
import { addPeriods, labelGranularity, periodWindowEnd } from "@/lib/periods";

describe("addPeriods", () => {
  it("steps in the unit the run was fitted at", () => {
    expect(addPeriods("2026-01-01", 3, "daily")).toBe("2026-01-04");
    expect(addPeriods("2026-01-01", 3, "weekly")).toBe("2026-01-22");
    expect(addPeriods("2026-01-01", 3, "monthly")).toBe("2026-04-01");
    expect(addPeriods("2026-01-01", 3, "quarterly")).toBe("2026-10-01");
  });

  it("crosses year boundaries", () => {
    expect(addPeriods("2025-11-01", 3, "monthly")).toBe("2026-02-01");
  });

  it("ignores a time component and survives an unparseable date", () => {
    expect(addPeriods("2026-01-01T12:00:00", 1, "monthly")).toBe("2026-02-01");
    expect(addPeriods("not-a-date", 1, "monthly")).toBe("not-a-date");
  });
});

describe("periodWindowEnd", () => {
  it("counts the starting period, so six months ends in the sixth", () => {
    expect(periodWindowEnd("2026-01-01", 6, "monthly")).toBe("2026-06-01");
    expect(periodWindowEnd("2026-01-01", 1, "monthly")).toBe("2026-01-01");
  });

  it("never runs backwards from a zero or negative count", () => {
    expect(periodWindowEnd("2026-01-01", 0, "monthly")).toBe("2026-01-01");
  });
});

describe("labelGranularity", () => {
  it("asks for day precision only where months would collapse", () => {
    expect(labelGranularity("daily")).toBe("day");
    expect(labelGranularity("weekly")).toBe("day");
    expect(labelGranularity("monthly")).toBe("month");
    expect(labelGranularity("quarterly")).toBe("month");
    expect(labelGranularity(null)).toBe("month");
  });

  it("drives the range label", () => {
    expect(formatDateRange("2026-01-05", "2026-01-19", "day")).toBe("Jan 5 – Jan 19");
    expect(formatDateRange("2026-01-05", "2026-06-19")).toBe("Jan 2026 – Jun 2026");
  });
});
