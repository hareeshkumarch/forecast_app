"use client";

import { useMemo } from "react";

import { EChart, type ChartOption } from "@/components/charts/echart";
import {
  axisLabel,
  chartColors,
  colorVar,
  sequentialRamp,
  sequentialRampVars,
  tooltipHeader,
  tooltipRow,
  tooltipStyle,
} from "@/lib/chart-theme";
import { formatCompact, formatDayMonth, formatMonth } from "@/lib/format";
import { useThemeRevision } from "@/stores/prefs-store";
import type { CoverageResponse } from "@/types/api";

const ROW_HEIGHT = 13;
const MIN_HEIGHT = 220;
const MAX_LABEL_CHARS = 22;

const NO_ROW = 0;
const REPORTED_ZERO = 1;
const FIRST_RAMP_BAND = 2;

/** [x, y, band, raw value] — the band is what gets coloured, the value is what gets said. */
type Cell = [number, number, number, number | null];
type CellItem = { value: Cell; itemStyle?: { borderColor: string; borderWidth: number } };

/**
 * Quartiles of the values that are actually there.
 *
 * Equal-width bands put almost every cell of a skewed demand panel in the
 * bottom step, which is the same picture as no ramp at all. Quantiles spend
 * the four steps where the series actually differ.
 */
function thresholds(values: number[]): number[] {
  if (values.length === 0) return [0, 0, 0];
  const sorted = [...values].sort((a, b) => a - b);
  const at = (q: number) => sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))] ?? 0;
  return [at(0.25), at(0.5), at(0.75)];
}

function band(value: number | null, cuts: number[]): number {
  if (value === null) return NO_ROW;
  if (value === 0) return REPORTED_ZERO;
  const step = cuts.findIndex((cut) => value <= cut);
  return FIRST_RAMP_BAND + (step === -1 ? cuts.length : step);
}

export function CoverageGrid({
  coverage,
  currency = true,
}: {
  coverage: CoverageResponse;
  currency?: boolean;
}) {
  // The palette lives in CSS variables, so it has to be re-read when the theme
  // changes: nothing about a canvas repaints itself.
  const revision = useThemeRevision();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const colors = useMemo(() => chartColors(), [revision]);
  const ramp = useMemo(() => sequentialRamp(colors), [colors]);

  const option = useMemo<ChartOption>(() => {
    const fine = coverage.frequency === "daily" || coverage.frequency === "weekly";
    const period = (iso: string) => (fine ? formatDayMonth(iso) : formatMonth(iso));

    const present = coverage.rows.flatMap((row) =>
      row.values.filter((value): value is number => value !== null && value > 0),
    );
    const cuts = thresholds(present);

    // A reported zero is given the cell outline that a magnitude cell gets from
    // its fill: without it, the palest state sits at 1.15:1 against the surface
    // and a month somebody reported as nil is indistinguishable from a month
    // they never sent — which is the one distinction this grid exists to make.
    const cells: CellItem[] = [];
    coverage.rows.forEach((row, y) => {
      row.values.forEach((value, x) => {
        const cell: Cell = [x, y, band(value, cuts), value];
        cells.push(
          cell[2] === REPORTED_ZERO
            ? { value: cell, itemStyle: { borderColor: colors.borderStrong, borderWidth: 1 } }
            : { value: cell },
        );
      });
    });

    const bandColors = [colors.surface, colors.surfaceMuted, ...ramp];

    return {
      grid: { left: 8, right: 12, top: 8, bottom: 24, containLabel: true },
      tooltip: {
        ...tooltipStyle(colors),
        formatter: (params: unknown) => {
          const { data } = params as { data: CellItem };
          const [x, y, cellBand, value] = data.value;
          const row = coverage.rows[y];
          if (!row) return "";
          const reading =
            cellBand === NO_ROW
              ? "no row for this period"
              : value === 0
                ? "reported zero"
                : formatCompact(value ?? 0, currency);
          return [
            tooltipHeader(row.series_id, colors),
            tooltipRow(
              bandColors[cellBand] ?? colors.textMuted,
              period(coverage.periods[x] ?? ""),
              reading,
              colors,
            ),
            tooltipRow(
              colors.textMuted,
              "Periods present",
              `${row.observations} of ${coverage.periods.length}`,
              colors,
            ),
          ].join("");
        },
      },
      xAxis: {
        type: "category",
        data: coverage.periods.map(period),
        axisLabel: { ...axisLabel(colors), hideOverlap: true },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      yAxis: {
        type: "category",
        inverse: true,
        data: coverage.rows.map((row) =>
          row.series_id.length > MAX_LABEL_CHARS
            ? `${row.series_id.slice(0, MAX_LABEL_CHARS - 1)}…`
            : row.series_id,
        ),
        axisLabel: {
          ...axisLabel(colors),
          // Every row is named. A grid whose rows are anonymous shows that
          // something is patchy without saying which line to go and fix.
          interval: 0,
          fontSize: coverage.rows.length > 60 ? 8 : 10,
        },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      visualMap: {
        type: "piecewise",
        show: false,
        dimension: 2,
        pieces: bandColors.map((color, index) => ({ value: index, color })),
      },
      series: [
        {
          type: "heatmap",
          data: cells,
          progressive: 5000,
          itemStyle: { borderColor: colors.surface, borderWidth: 1, borderRadius: 1 },
          emphasis: { itemStyle: { borderColor: colors.textPrimary, borderWidth: 1 } },
        },
      ],
    } satisfies ChartOption;
  }, [coverage, currency, colors, ramp]);

  const height = Math.max(MIN_HEIGHT, coverage.rows.length * ROW_HEIGHT + 48);

  return (
    <div>
      <div style={{ height }}>
        <EChart
          option={option}
          fill
          ariaLabel={`Coverage of ${coverage.rows.length} series over ${coverage.periods.length} periods. Empty cells are periods a series has no row for; shaded cells are periods with data, darker where the value is larger.`}
        />
      </div>
      <CoverageLegend />
    </div>
  );
}

function CoverageLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-1 pt-2 text-caption text-text-muted">
      <Swatch color={colorVar("surface")} border={colorVar("border")} label="No row" />
      <Swatch
        color={colorVar("surfaceMuted")}
        border={colorVar("borderStrong")}
        label="Reported zero"
      />
      <span className="flex items-center gap-1.5">
        <span className="flex">
          {sequentialRampVars().map((color) => (
            <span
              key={color}
              className="h-2.5 w-3.5 first:rounded-l-[2px] last:rounded-r-[2px]"
              style={{ background: color }}
            />
          ))}
        </span>
        <span>Smaller to larger</span>
      </span>
    </div>
  );
}

function Swatch({
  color,
  border,
  label,
}: {
  color: string;
  border: string;
  label: string;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className="h-2.5 w-2.5 rounded-[2px]"
        style={{ background: color, boxShadow: `inset 0 0 0 1px ${border}` }}
      />
      <span>{label}</span>
    </span>
  );
}
