import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useSortedRows } from "@/components/ui/sortable-header";

interface Row {
  region: string;
  forecast_value: number;
  accuracy: number | null;
}

const ROWS: Row[] = [
  { region: "Europe", forecast_value: 300, accuracy: 90.4 },
  { region: "Asia Pacific", forecast_value: 600, accuracy: null },
  { region: "North America", forecast_value: 1_000, accuracy: 88.1 },
];

type Key = "region" | "forecast_value" | "accuracy";

function setup(initialKey: Key = "forecast_value") {
  return renderHook(() =>
    useSortedRows<Row, Key>(ROWS, { key: initialKey, direction: "desc" }, (row, key) => row[key]),
  );
}

describe("table sorting", () => {
  it("starts on the requested column and direction", () => {
    const { result } = setup();
    expect(result.current.sorted.map((row) => row.forecast_value)).toEqual([1_000, 600, 300]);
  });

  it("flips direction when the same column is toggled", () => {
    const { result } = setup();

    act(() => result.current.toggle("forecast_value"));

    expect(result.current.sort.direction).toBe("asc");
    expect(result.current.sorted.map((row) => row.forecast_value)).toEqual([300, 600, 1_000]);
  });

  it("sorts text columns alphabetically", () => {
    const { result } = setup();

    act(() => result.current.toggle("region"));

    expect(result.current.sorted[0]?.region).toBe("North America");
  });

  it("sinks missing values to the bottom instead of treating them as zero", () => {
    const { result } = setup();

    act(() => result.current.toggle("accuracy"));

    expect(result.current.sorted.at(-1)?.accuracy).toBeNull();
    expect(result.current.sorted[0]?.accuracy).toBe(90.4);
  });

  it("keeps missing values last in ascending order too", () => {
    const { result } = setup();

    act(() => result.current.toggle("accuracy"));
    act(() => result.current.toggle("accuracy"));

    expect(result.current.sort.direction).toBe("asc");
    expect(result.current.sorted.at(-1)?.accuracy).toBeNull();
    expect(result.current.sorted[0]?.accuracy).toBe(88.1);
  });

  it("leaves the source array untouched", () => {
    const { result } = setup();
    act(() => result.current.toggle("region"));

    expect(ROWS.map((row) => row.region)).toEqual(["Europe", "Asia Pacific", "North America"]);
  });
});
