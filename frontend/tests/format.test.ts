import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatCompact,
  formatDateRange,
  formatMetric,
  formatMonth,
  formatPercent,
  formatSignedPercent,
  humanizeModel,
} from "@/lib/format";

describe("formatCompact", () => {
  it("matches the backend's compact notation", () => {
    expect(formatCompact(24_240_000)).toBe("$24.24M");
    expect(formatCompact(930_600)).toBe("$930.6K");
    expect(formatCompact(2_480_000_000)).toBe("$2.48B");
    expect(formatCompact(842)).toBe("$842");
  });

  it("handles negatives with the sign outside the symbol", () => {
    expect(formatCompact(-102_100)).toBe("-$102.1K");
  });

  it("can drop the currency symbol", () => {
    expect(formatCompact(18_240, false)).toBe("18.2K");
  });

  it("renders an em dash for missing or non-finite values", () => {
    expect(formatCompact(null)).toBe("—");
    expect(formatCompact(undefined)).toBe("—");
    expect(formatCompact(Number.NaN)).toBe("—");
    expect(formatCompact(Number.POSITIVE_INFINITY)).toBe("—");
  });

  it("carries on past billions", () => {
    expect(formatCompact(33_160_310_000_000)).toBe("$33.16T");
    expect(formatCompact(4.2e12)).toBe("$4.20T");
  });

  it("keeps the significant digits of a value below one", () => {
    expect(formatCompact(0.42)).toBe("$0.42");
    expect(formatCompact(0.0031)).toBe("$0.0031");
    expect(formatCompact(3.1e-6)).toBe("$3.10e-6");
    expect(formatCompact(0)).toBe("$0");
  });

  it("rounds a tie the way the backend does, so a card and its report agree", () => {
    expect(formatCompact(1250)).toBe("$1.3K");
    expect(formatCompact(1_250_000_000_000)).toBe("$1.25T");
  });

  it("never renders a real magnitude as a bare zero or a blank", () => {
    for (let exponent = -12; exponent <= 15; exponent += 1) {
      const rendered = formatCompact(1.7 * 10 ** exponent);
      expect(rendered, `1.7e${exponent}`).not.toBe("$0");
      expect(rendered, `1.7e${exponent}`).not.toBe("—");
    }
  });
});

describe("percentages", () => {
  it("formats plain and signed percentages", () => {
    expect(formatPercent(90.9)).toBe("90.9%");
    expect(formatSignedPercent(23.4)).toBe("+23.4%");
    expect(formatSignedPercent(-17.0)).toBe("-17.0%");
  });

  it("returns an em dash rather than 0% for missing data", () => {
    expect(formatPercent(null)).toBe("—");
    expect(formatSignedPercent(null)).toBe("—");
  });
});

describe("dates", () => {
  it("parses ISO dates as UTC so the label cannot shift a day", () => {
    expect(formatMonth("2026-01-01")).toBe("Jan 2026");
    expect(formatMonth("2025-12-01T00:00:00")).toBe("Dec 2025");
  });

  it("formats a range, falling back when either end is missing", () => {
    expect(formatDateRange("2026-01-01", "2026-06-01")).toBe("Jan 2026 – Jun 2026");
    expect(formatDateRange(null, "2026-06-01")).toBe("All dates");
  });
});

describe("formatMetric", () => {
  it("respects the unit the backend reported", () => {
    expect(formatMetric(90.9, "percent")).toBe("90.9%");
    expect(formatMetric(-1.2, "percentage_points")).toBe("-1.2pp");
    expect(formatMetric(4, "count")).toBe("4");
    expect(formatMetric(5.839, "ratio")).toBe("5.84x");
    expect(formatMetric(5.63, "std_dev")).toBe("5.6σ");
    expect(formatMetric(930_600, "absolute")).toBe("$930.6K");
  });
});

describe("misc", () => {
  it("humanizes model identifiers", () => {
    expect(humanizeModel("holt_winters")).toBe("Holt Winters");
    expect(humanizeModel("gradient_boosting")).toBe("Gradient Boosting");
    expect(humanizeModel(null)).toBe("—");
  });

  it("formats byte sizes", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(21 * 1024 * 1024)).toBe("21.0 MB");
  });
});
