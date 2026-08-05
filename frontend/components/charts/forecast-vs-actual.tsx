"use client";


import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { LineChart, MoreHorizontal } from "lucide-react";
import { useMemo } from "react";

import { EChart, type ChartOption } from "@/components/charts/echart";
import {
  Card,
  EmptyState,
  ErrorState,
  MENU_CONTENT,
  MENU_ITEM,
  PanelHeader,
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
import { labelGranularity } from "@/lib/periods";
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
): { sliced: ForecastPointsResponse["points"]; offset: number; trimmed: number } {
  const horizon = points.length - boundary;
  const historyToShow = Math.max(18, horizon * 3);
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
): ChartOption {
  const { confidence_level: confidence } = data;

  // A daily run stamped with month labels repeats "Mar 2026" thirty times.
  const period =
    labelGranularity(data.frequency) === "day" ? formatDayMonth : formatMonth;

  const rawBoundary = data.boundary_index ?? data.points.length;
  const { sliced: points, offset } = displayWindow(data.points, rawBoundary);
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
    
    
    grid: { left: 8, right: 14, top: 42, bottom: points.length > 40 ? 26 : 4, containLabel: true },
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
        data: bandBase,
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
        data: bandSpan,
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

export function ForecastVsActual() {
  const { data: summary } = useSummary();
  const view = useUiStore((state) => state.view);
  const runId = summary?.run_id ?? null;

  const { data, isLoading, isError, error, refetch } = useForecastPoints(runId);

  const revision = useThemeRevision();
  const option = useMemo(
    () => (data ? buildOption(data, view, chartColors()) : null),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, view, revision],
  );

  return (
    <Card className="flex min-w-0 flex-col">
      <PanelHeader
        title="Forecast vs Actual"
        subtitle={summary?.run_name ?? undefined}
        actions={
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
              <DropdownMenu.Content
                align="end"
                sideOffset={4}
                className={MENU_CONTENT}
              >
                <DropdownMenu.Item
                  disabled={!runId}
                  onSelect={() => runId && downloadExport(runId, "csv")}
                  className={MENU_ITEM}
                >
                  Download series (CSV)
                </DropdownMenu.Item>
                <DropdownMenu.Item
                  disabled={!runId}
                  onSelect={() => runId && downloadExport(runId, "json")}
                  className={MENU_ITEM}
                >
                  Download run detail (JSON)
                </DropdownMenu.Item>
                <DropdownMenu.Item
                  onSelect={() => void refetch()}
                  className={MENU_ITEM}
                >
                  Refresh
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        }
      />

      <div className="min-h-0 flex-1 px-3 pb-3">
        {isLoading ? (
          <div className="space-y-2 px-1 pt-2" aria-hidden>
            <Skeleton className="h-3 w-40" />
            <Skeleton className="chart-box w-full rounded-[9px]" />
          </div>
        ) : isError ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : option && data && data.points.length > 0 ? (
          <EChart option={option} ariaLabel="Forecast versus actual over time" />
        ) : (
          <EmptyState
            className="chart-box"
            icon={LineChart}
            // Without a run there is no window to widen, and saying so sends a
            // new user hunting through a date filter for data that was never
            // there.
            title={runId ? "Nothing in this window" : "No forecast yet"}
            message={
              runId
                ? "No period falls inside the selected range — widen it to see the series."
                : "Run a forecast and its history and horizon will be plotted here."
            }
          />
        )}
      </div>
    </Card>
  );
}
