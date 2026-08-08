"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { LineChart, MoreHorizontal } from "lucide-react";
import { useMemo, useState } from "react";

import { EChart, type ChartOption } from "@/components/charts/echart";
import { Panel } from "@/components/ui/panel";
import {
  MENU_CONTENT,
  MENU_ITEM,
  Skeleton,
} from "@/components/ui/primitives";
import { downloadExport, useForecastPoints, useSummary } from "@/hooks/use-dashboard";
import {
  type ChartPalette,
  axisLabel,
  axisLine,
  axisValueFormatter,
  chartColors,
  splitLine,
  tooltipHeader,
  tooltipRow,
  tooltipStyle,
} from "@/lib/chart-theme";
import { formatCompact, formatDayMonth, formatMonth } from "@/lib/format";
import { labelGranularity, periodsPerYear } from "@/lib/periods";
import { cn } from "@/lib/utils";
import { useThemeRevision } from "@/stores/prefs-store";
import { useUiStore } from "@/stores/ui-store";
import type { ForecastPointsResponse, ForecastView } from "@/types/api";

const VIEW_FIELD: Record<ForecastView, "forecast" | "best_case" | "worst_case"> = {
  base: "forecast",
  best: "best_case",
  worst: "worst_case",
};

function displayWindow(
  points: ForecastPointsResponse["points"],
  boundary: number,
  history?: number,
): { sliced: ForecastPointsResponse["points"]; offset: number; trimmed: number } {
  const horizon = points.length - boundary;
  const historyToShow = history ?? Math.max(18, horizon * 3);
  const offset = Math.max(0, boundary - historyToShow);

  return {
    sliced: points.slice(offset),
    offset,
    trimmed: offset,
  };
}

function buildOption(
  data: ForecastPointsResponse,
  view: ForecastView,
  colors: ChartPalette,
  options: { history?: number; band?: boolean } = {},
): ChartOption {
  const { confidence_level: confidence } = data;

  const period =
    labelGranularity(data.frequency) === "day" ? formatDayMonth : formatMonth;

  const rawBoundary = data.boundary_index ?? data.points.length;
  const { sliced: points, offset } = displayWindow(data.points, rawBoundary, options.history);
  const boundaryIndex = rawBoundary - offset;

  const labels = points.map((point) => period(point.period));
  const actuals = points.map((point) => point.actual);

  const field = VIEW_FIELD[view];
  const boundary = boundaryIndex ?? points.length;

  const lastActualIndex = boundary - 1;
  const lastActual = lastActualIndex >= 0 ? points[lastActualIndex]?.actual ?? null : null;

  const forecasts = points.map((point, index) => {
    if (index === lastActualIndex) return lastActual;
    if (index < boundary) return null;
    return point[field] ?? point.forecast;
  });

  const bandBase = points.map((point, index) => {
    if (index === lastActualIndex) return lastActual;
    return index < boundary ? null : point.lower_bound;
  });
  const bandSpan = points.map((point, index) => {
    if (index === lastActualIndex) return 0;
    if (index < boundary) return null;
    if (point.upper_bound === null || point.lower_bound === null) return null;
    return point.upper_bound - point.lower_bound;
  });

  const boundaryLabel = points[boundary]?.period;

  return {
    backgroundColor: "transparent",
    animation: false,

    // The band is at its widest on the last period, and with only 14px to the
    // card edge it ended in a wall that read as a clipped chart. The extra room
    // lets the horizon close inside the frame instead of against it.
    grid: { left: 8, right: 28, top: 42, bottom: points.length > 40 ? 26 : 4, containLabel: true },
    dataZoom: [
      { type: "inside", throttle: 50, zoomOnMouseWheel: "shift", moveOnMouseWheel: false },
      ...(points.length > 40
        ? [
            {
              type: "slider" as const,
              height: 16,
              bottom: 2,
              borderColor: colors.border,
              fillerColor: colors.accentSoft,
              handleStyle: { color: colors.accent },
              moveHandleStyle: { color: colors.border },
              textStyle: { color: colors.textMuted, fontSize: 9 },
              dataBackground: {
                lineStyle: { color: colors.borderStrong },
                areaStyle: { color: colors.surfaceMuted },
              },
              selectedDataBackground: {
                lineStyle: { color: colors.accent },
                areaStyle: { color: colors.accentSoft },
              },
            },
          ]
        : []),
    ],
    legend: {
      show: true,
      top: 0,
      left: 0,
      itemGap: 16,
      itemWidth: 14,
      itemHeight: 2,
      icon: "roundRect",
      textStyle: { ...axisLabel(colors), fontSize: 11, color: colors.textSecondary },
      data: ["Actual", "Forecast", `${Math.round(confidence * 100)}% confidence`],
    },
    tooltip: {
      ...tooltipStyle(colors),
      trigger: "axis",
      confine: true,
      axisPointer: {
        type: "line",
        lineStyle: { color: colors.borderStrong, width: 1, type: "dashed" },
      },
      formatter: (params: unknown) => {
        const rows = Array.isArray(params) ? params : [params];
        const first = rows[0] as { dataIndex: number } | undefined;
        if (!first) return "";

        const index = first.dataIndex;
        const point = points[index];
        if (!point) return "";

        let html = tooltipHeader(period(point.period), colors);

        if (point.actual !== null) {
          html += tooltipRow(colors.navy, "Actual", formatCompact(point.actual), colors);
        }
        const forecastValue = point[field] ?? point.forecast;
        if (forecastValue !== null && index >= boundary) {
          html += tooltipRow(colors.accent, "Forecast", formatCompact(forecastValue), colors);
        }
        if (point.lower_bound !== null && point.upper_bound !== null) {
          html += tooltipRow(
            colors.sand,
            "Range",
            `${formatCompact(point.lower_bound)} – ${formatCompact(point.upper_bound)}`,
            colors,
          );
        }
        return html;
      },
    },
    xAxis: {
      type: "category",
      data: labels,
      boundaryGap: false,
      axisLine: axisLine(colors),
      axisTick: { show: false },

      axisLabel: { ...axisLabel(colors), margin: 10, hideOverlap: true },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { ...axisLabel(colors), margin: 10, formatter: axisValueFormatter(true) },
      splitLine: splitLine(colors),
      splitNumber: 4,
    },
    series: [
      {
        name: `${Math.round(confidence * 100)}% confidence`,
        type: "line",
        data: options.band === false ? [] : bandBase,
        lineStyle: { opacity: 0 },

        itemStyle: { color: colors.sand },
        stack: "confidence",
        symbol: "none",
        silent: true,
        z: 1,
      },
      {
        name: "confidence-span",
        type: "line",
        data: options.band === false ? [] : bandSpan,
        lineStyle: { opacity: 0 },
        stack: "confidence",
        symbol: "none",
        silent: true,
        z: 1,
        areaStyle: { color: colors.sand, opacity: 0.22 },
        legendHoverLink: false,
      },
      {
        name: "Actual",
        type: "line",
        data: actuals,
        showSymbol: false,
        smooth: 0.18,
        lineStyle: { color: colors.navy, width: 1.9 },
        itemStyle: { color: colors.navy },
        connectNulls: false,
        z: 3,
        ...(boundaryLabel
          ? {
              markLine: {
                silent: true,
                symbol: "none",
                animation: false,
                label: {
                  show: true,
                  position: "end",
                  formatter: "Forecast",
                  fontSize: 10,
                  color: colors.textMuted,

                  rotate: 0,
                  distance: [0, 6],
                  align: "center",
                },
                lineStyle: { color: colors.borderStrong, width: 1, type: "dashed" },
                data: [{ xAxis: period(boundaryLabel) }],
              },
            }
          : {}),
      },
      {
        name: "Forecast",
        type: "line",
        data: forecasts,
        showSymbol: false,
        smooth: 0.18,
        lineStyle: { color: colors.accent, width: 1.9, type: "dashed" },
        itemStyle: { color: colors.accent },
        connectNulls: false,
        z: 3,
      },
    ],
  };
}

export function ForecastVsActual({
  seriesId,
  title = "Forecast vs Actual",
  subtitle,
  showActions = true,
}: {
  seriesId?: string | null;
  title?: string;
  subtitle?: string;
  showActions?: boolean;
} = {}) {
  const { data: summary } = useSummary();
  const view = useUiStore((state) => state.view);
  const runId = summary?.run_id ?? null;

  const { data, isLoading, isError, error, refetch } = useForecastPoints(runId, seriesId);

  const revision = useThemeRevision();
  const option = useMemo(
    () => (data ? buildOption(data, view, chartColors()) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, view, revision],
  );

  const empty = data && data.points.length > 0 ? null : true;

  return (
    <Panel
      title={title}
      subtitle={subtitle ?? summary?.run_name ?? undefined}
      state={{ isLoading, isError, error, refetch: () => void refetch() }}
      isEmpty={Boolean(empty)}
      empty={{
        icon: LineChart,

        title: runId ? "Nothing in this window" : "No forecast yet",
        message: !runId
          ? "Run a forecast and its history and horizon will be plotted here."
          : seriesId
            ? "This series has no periods inside the selected range."
            : "No period falls inside the selected range — widen it to see the series.",
      }}
      enlarged={
        data
          ? {
              title,
              description: summary?.run_name ?? undefined,
              content: <Enlarged data={data} view={view} />,
            }
          : undefined
      }
      actions={
        !showActions ? null : (
          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button
                type="button"
                aria-label="Panel actions"
                className={cn(
                  "inline-flex h-11 w-11 items-center justify-center rounded-chip sm:h-6 sm:w-6",
                  "text-text-muted transition-colors duration-fast hover:bg-surface-muted hover:text-text-primary",
                )}
              >
                <MoreHorizontal className="h-4 w-4" aria-hidden />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content align="end" sideOffset={4} className={MENU_CONTENT}>
                <DropdownMenu.Item
                  disabled={!runId}
                  onSelect={() => runId && downloadExport(runId, "csv")}
                  className={MENU_ITEM}
                >
                  Download the numbers (CSV)
                </DropdownMenu.Item>
                <DropdownMenu.Item
                  disabled={!runId}
                  onSelect={() => runId && downloadExport(runId, "pdf")}
                  className={MENU_ITEM}
                >
                  Download the report (PDF)
                </DropdownMenu.Item>
                <DropdownMenu.Item onSelect={() => void refetch()} className={MENU_ITEM}>
                  Refresh
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        )
      }
      skeleton={
        <div className="space-y-2 px-1 pt-2" aria-hidden>
          <Skeleton className="h-3 w-40" />
          <Skeleton className="chart-box w-full rounded-[9px]" />
        </div>
      }
    >
      {option ? <EChart option={option} ariaLabel="Forecast versus actual over time" /> : null}
    </Panel>
  );
}

const WINDOWS = [
  { key: "working", label: "Recent" },
  { key: "year", label: "Last year" },
  { key: "all", label: "Everything" },
] as const;

function Enlarged({ data, view }: { data: ForecastPointsResponse; view: ForecastView }) {
  const [window, setWindow] = useState<(typeof WINDOWS)[number]["key"]>("working");
  const [band, setBand] = useState(true);
  const revision = useThemeRevision();

  const history =
    window === "all"
      ? data.points.length
      : window === "year"
        ? periodsPerYear(data.frequency)
        : undefined;

  const option = useMemo(
    () => buildOption(data, view, chartColors(), { history, band }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, view, history, band, revision],
  );

  const boundary = data.boundary_index ?? data.points.length;
  const rows = useMemo(
    () => [...data.points].reverse().map((point, index) => ({
      point,
      ahead: data.points.length - 1 - index >= boundary,
    })),
    [data.points, boundary],
  );

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1">
          {WINDOWS.map((option_) => (
            <button
              key={option_.key}
              type="button"
              onClick={() => setWindow(option_.key)}
              aria-pressed={window === option_.key}
              className={cn(
                "rounded-chip border px-2 py-1 text-caption font-medium transition-colors duration-fast",
                window === option_.key
                  ? "border-accent bg-accent-soft text-accent"
                  : "border-border text-text-secondary hover:bg-surface-muted",
              )}
            >
              {option_.label}
            </button>
          ))}
        </div>

        <label className="flex cursor-pointer items-center gap-1.5 text-caption text-text-secondary">
          <input
            type="checkbox"
            checked={band}
            onChange={(event) => setBand(event.target.checked)}
            className="h-3.5 w-3.5 accent-[var(--accent)]"
          />
          Show the likely range
        </label>
      </div>

      <div className="h-[min(46vh,380px)]">
        <EChart option={option} ariaLabel="Forecast versus actual, enlarged" fill />
      </div>

      <div className="scroll-thin max-h-[240px] overflow-y-auto rounded-card border border-border">
        <table className="w-full border-collapse text-meta">
          <thead className="sticky top-0 bg-surface">
            <tr className="border-b border-border text-caption text-text-muted">
              <th className="px-3 py-2 text-left font-medium">Period</th>
              <th className="px-3 py-2 text-right font-medium">Actual</th>
              <th className="px-3 py-2 text-right font-medium">Forecast</th>
              <th className="px-3 py-2 text-right font-medium">Likely range</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ point, ahead }) => (
              <tr key={point.period} className="border-b border-border last:border-0">
                <td className="px-3 py-1.5 text-text-primary">
                  {point.period}
                  {ahead ? (
                    <span className="ml-1.5 text-caption text-text-muted">ahead</span>
                  ) : null}
                </td>
                <td className="px-3 py-1.5 text-right num text-text-primary">
                  {point.actual === null ? "—" : formatCompact(point.actual)}
                </td>
                <td className="px-3 py-1.5 text-right num text-text-secondary">
                  {point.forecast === null ? "—" : formatCompact(point.forecast)}
                </td>
                <td className="px-3 py-1.5 text-right num text-text-muted">
                  {point.lower_bound === null || point.upper_bound === null
                    ? "—"
                    : `${formatCompact(point.lower_bound)} – ${formatCompact(point.upper_bound)}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
