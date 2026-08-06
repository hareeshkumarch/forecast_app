"use client";

import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import { EChart, type ChartOption } from "@/components/charts/echart";
import { Panel } from "@/components/ui/panel";
import {
  Badge,
  EmptyState,
  Input,
  Skeleton,
} from "@/components/ui/primitives";
import { useBreakdown } from "@/hooks/use-dashboard";
import {
  axisLabel,
  categoricalPalette,
  chartColors,
  splitLine,
  tooltipStyle,
} from "@/lib/chart-theme";
import { formatCompact, formatPercent, formatSignedPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useThemeRevision } from "@/stores/prefs-store";
import type { BreakdownRef, BreakdownRow } from "@/types/api";

/**
 * Past this many slices a doughnut is a colour wheel nobody can read, so the
 * panel draws bars instead. Chosen from what the eye can do, not from the data
 * — every dataset gets the same treatment at the same size.
 */
const READABLE_SLICES = 7;

/** Rows drawn in the panel before the rest are left to the enlarged view. */
const PANEL_ROWS = 8;

export function BreakdownPanel({ breakdown }: { breakdown: BreakdownRef }) {
  const { data, isLoading, isError, error, refetch } = useBreakdown(breakdown.column);
  const rows = data?.rows ?? [];
  const currency = data?.currency ?? true;
  const count = `${rows.length.toLocaleString()} ${rows.length === 1 ? "value" : "values"}`;

  return (
    <Panel
      title={`Forecast by ${breakdown.label}`}
      subtitle={rows.length > 0 ? `${count}, largest first` : "Where the forecast comes from"}
      state={{ isLoading, isError, error, refetch: () => void refetch() }}
      isEmpty={rows.length === 0}
      empty={{
        title: `No ${breakdown.label.toLowerCase()} to show`,
        message: "This forecast produced no split for that column.",
      }}
      enlarged={{
        title: `Forecast by ${breakdown.label}`,
        description: `${count} · ${formatCompact(data?.total ?? 0, currency)} in total`,
        content: <Enlarged rows={rows} currency={currency} label={breakdown.label} />,
      }}
      skeleton={
        <div className="space-y-2.5 px-1 pt-2" aria-hidden>
          {Array.from({ length: 5 }).map((_, index) => (
            <Skeleton key={index} className="h-5 w-full" />
          ))}
        </div>
      }
    >
      <BreakdownChart
        rows={rows.slice(0, PANEL_ROWS)}
        currency={currency}
        ariaLabel={`Forecast by ${breakdown.label}`}
      />
    </Panel>
  );
}

/**
 * The shape follows the data: a handful of values reads best as a doughnut,
 * a long tail as ranked bars. Both are the same numbers.
 */
function BreakdownChart({
  rows,
  currency,
  ariaLabel,
}: {
  rows: BreakdownRow[];
  currency: boolean;
  ariaLabel: string;
}) {
  const revision = useThemeRevision();
  const option = useMemo(
    () => buildOption(rows, currency),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, currency, revision],
  );

  return <EChart option={option} className="chart-box" ariaLabel={ariaLabel} />;
}

function buildOption(rows: BreakdownRow[], currency: boolean): ChartOption {
  const colors = chartColors();
  const palette = categoricalPalette();

  if (rows.length <= READABLE_SLICES) {
    return {
      tooltip: { ...tooltipStyle(colors), trigger: "item" },
      legend: {
        orient: "vertical",
        right: 0,
        top: "middle",
        textStyle: { ...axisLabel(colors), fontSize: 11 },
        itemWidth: 8,
        itemHeight: 8,
      },
      series: [
        {
          type: "pie",
          radius: ["58%", "82%"],
          center: ["32%", "50%"],
          avoidLabelOverlap: true,
          label: { show: false },
          itemStyle: { borderWidth: 2, borderColor: colors.surface },
          data: rows.map((row, index) => ({
            name: row.label,
            value: Number(row.forecast.toFixed(2)),
            itemStyle: { color: palette[index % palette.length] },
          })),
        },
      ],
    };
  }

  // Ranked bars, drawn top-down: echarts stacks a category axis upward, so the
  // rows are reversed to put the largest at the top where it is looked for.
  const ordered = [...rows].reverse();
  return {
    grid: { left: 4, right: 16, top: 8, bottom: 4, containLabel: true },
    tooltip: { ...tooltipStyle(colors), trigger: "axis", axisPointer: { type: "shadow" } },
    xAxis: {
      type: "value",
      axisLabel: { ...axisLabel(colors), formatter: (v: number) => formatCompact(v, currency) },
      splitLine: splitLine(colors),
    },
    yAxis: {
      type: "category",
      data: ordered.map((row) => row.label),
      axisLabel: axisLabel(colors),
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series: [
      {
        type: "bar",
        data: ordered.map((row) => Number(row.forecast.toFixed(2))),
        itemStyle: { color: colors.accent, borderRadius: [0, 3, 3, 0] },
        barMaxWidth: 14,
      },
    ],
  };
}

/**
 * The enlarged view: the whole split, searchable, with the numbers beside the
 * picture. A panel has room for the shape; this has room for the detail.
 */
function Enlarged({
  rows,
  currency,
  label,
}: {
  rows: BreakdownRow[];
  currency: boolean;
  label: string;
}) {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<"forecast" | "change" | "accuracy" | "label">("forecast");

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const matched = needle
      ? rows.filter((row) => row.label.toLowerCase().includes(needle))
      : [...rows];

    return matched.sort((a, b) => {
      if (sort === "label") return a.label.localeCompare(b.label);
      // A missing number sorts last whatever the column: an unknown is not a
      // small value, and putting it at the top buries what is known.
      const pick = (row: BreakdownRow) =>
        sort === "change" ? row.change : sort === "accuracy" ? row.accuracy : row.forecast;
      const [left, right] = [pick(a), pick(b)];
      if (left === null) return right === null ? 0 : 1;
      if (right === null) return -1;
      return right - left;
    });
  }, [rows, search, sort]);

  const scored = rows.some((row) => row.actual !== null);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[180px] flex-1">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted"
            aria-hidden
          />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder={`Find a ${label.toLowerCase()}`}
            aria-label={`Find a ${label.toLowerCase()}`}
            className="pl-8"
          />
        </div>
        <div className="flex flex-wrap gap-1">
          {(
            [
              ["forecast", "Largest"],
              ["change", "Fastest moving"],
              ["accuracy", "Least accurate"],
              ["label", "A–Z"],
            ] as const
          ).map(([value, text]) => (
            <button
              key={value}
              type="button"
              onClick={() => setSort(value)}
              aria-pressed={sort === value}
              className={cn(
                "rounded-chip border px-2 py-1 text-caption font-medium transition-colors duration-fast",
                sort === value
                  ? "border-accent bg-accent-soft text-accent"
                  : "border-border text-text-secondary hover:bg-surface-muted",
              )}
            >
              {text}
            </button>
          ))}
        </div>
      </div>

      {shown.length === 0 ? (
        <EmptyState title="Nothing matches" message={`No ${label.toLowerCase()} contains “${search}”.`} />
      ) : (
        <>
          <div className="h-[260px]">
            <BreakdownChart
              rows={shown.slice(0, 24)}
              currency={currency}
              ariaLabel={`Forecast by ${label}, enlarged`}
            />
          </div>

          <div className="scroll-thin max-h-[280px] overflow-y-auto rounded-card border border-border">
            <table className="w-full border-collapse text-meta">
              <thead className="sticky top-0 bg-surface">
                <tr className="border-b border-border text-caption text-text-muted">
                  <th className="px-3 py-2 text-left font-medium">{label}</th>
                  <th className="px-3 py-2 text-right font-medium">Forecast</th>
                  <th className="px-3 py-2 text-right font-medium">Share</th>
                  <th className="px-3 py-2 text-right font-medium">Trend</th>
                  {scored ? <th className="px-3 py-2 text-right font-medium">Actual</th> : null}
                  <th className="px-3 py-2 text-right font-medium">Accuracy</th>
                </tr>
              </thead>
              <tbody>
                {shown.map((row) => (
                  <tr key={row.label} className="border-b border-border last:border-0">
                    <td className="max-w-[220px] truncate px-3 py-1.5 text-text-primary">
                      {row.label}
                    </td>
                    <td className="px-3 py-1.5 text-right num text-text-primary">
                      {formatCompact(row.forecast, currency)}
                    </td>
                    <td className="px-3 py-1.5 text-right num text-text-secondary">
                      {formatPercent(row.share, 1)}
                    </td>
                    <td
                      className={cn(
                        "px-3 py-1.5 text-right num",
                        row.change === null
                          ? "text-text-muted"
                          : row.change >= 0
                            ? "text-positive"
                            : "text-negative",
                      )}
                    >
                      {row.change === null ? "—" : formatSignedPercent(row.change)}
                    </td>
                    {scored ? (
                      <td className="px-3 py-1.5 text-right num text-text-primary">
                        {row.actual === null ? "—" : formatCompact(row.actual, currency)}
                      </td>
                    ) : null}
                    <td className="px-3 py-1.5 text-right num text-text-secondary">
                      {row.accuracy_measured && row.accuracy !== null ? (
                        formatPercent(row.accuracy)
                      ) : (
                        <Badge tone="neutral">Estimated</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-caption text-text-muted">
            Showing {shown.length.toLocaleString()} of {rows.length.toLocaleString()}
            {shown.length > 24 ? " — the chart draws the top 24" : ""}.
          </p>
        </>
      )}
    </div>
  );
}
