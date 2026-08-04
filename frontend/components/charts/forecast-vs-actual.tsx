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
  AXIS_LABEL,
  AXIS_LINE,
  CHART_COLORS,
  SPLIT_LINE,
  TOOLTIP_STYLE,
  axisValueFormatter,
  tooltipHeader,
  tooltipRow,
} from "@/lib/chart-theme";
import { formatCompact, formatDayMonth, formatMonth } from "@/lib/format";
import { labelGranularity } from "@/lib/periods";
import { cn } from "@/lib/utils";
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

function buildOption(data: ForecastPointsResponse, view: ForecastView): ChartOption {
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
    
    
    grid: { left: 8, right: 14, top: 42, bottom: 4, containLabel: true },
    legend: {
      show: true,
      top: 0,
      left: 0,
      itemGap: 16,
      itemWidth: 14,
      itemHeight: 2,
      icon: "roundRect",
      textStyle: { ...AXIS_LABEL, fontSize: 11, color: CHART_COLORS.textSecondary },
      data: ["Actual", "Forecast", `${Math.round(confidence * 100)}% confidence`],
    },
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: "axis",
      confine: true,
      axisPointer: {
        type: "line",
        lineStyle: { color: CHART_COLORS.borderStrong, width: 1, type: "dashed" },
      },
      formatter: (params: unknown) => {
        const rows = Array.isArray(params) ? params : [params];
        const first = rows[0] as { dataIndex: number } | undefined;
        if (!first) return "";

        const index = first.dataIndex;
        const point = points[index];
        if (!point) return "";

        let html = tooltipHeader(period(point.period));

        if (point.actual !== null) {
          html += tooltipRow(CHART_COLORS.navy, "Actual", formatCompact(point.actual));
        }
        const forecastValue = point[field] ?? point.forecast;
        if (forecastValue !== null && index >= boundary) {
          html += tooltipRow(CHART_COLORS.accent, "Forecast", formatCompact(forecastValue));
        }
        if (point.lower_bound !== null && point.upper_bound !== null) {
          html += tooltipRow(
            CHART_COLORS.sand,
            "Range",
            `${formatCompact(point.lower_bound)} – ${formatCompact(point.upper_bound)}`,
          );
        }
        return html;
      },
    },
    xAxis: {
      type: "category",
      data: labels,
      boundaryGap: false,
      axisLine: AXIS_LINE,
      axisTick: { show: false },
      
      axisLabel: { ...AXIS_LABEL, margin: 10, hideOverlap: true },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { ...AXIS_LABEL, margin: 10, formatter: axisValueFormatter(true) },
      splitLine: SPLIT_LINE,
      splitNumber: 4,
    },
    series: [
      {
        name: `${Math.round(confidence * 100)}% confidence`,
        type: "line",
        data: bandBase,
        lineStyle: { opacity: 0 },
        
        
        itemStyle: { color: CHART_COLORS.sand },
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
        areaStyle: { color: CHART_COLORS.sand, opacity: 0.22 },
        legendHoverLink: false,
      },
      {
        name: "Actual",
        type: "line",
        data: actuals,
        showSymbol: false,
        smooth: 0.18,
        lineStyle: { color: CHART_COLORS.navy, width: 1.9 },
        itemStyle: { color: CHART_COLORS.navy },
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
                  color: CHART_COLORS.textMuted,
                  
                  
                  rotate: 0,
                  distance: [0, 6],
                  align: "center",
                },
                lineStyle: { color: CHART_COLORS.borderStrong, width: 1, type: "dashed" },
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
        lineStyle: { color: CHART_COLORS.accent, width: 1.9, type: "dashed" },
        itemStyle: { color: CHART_COLORS.accent },
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

  const option = useMemo(() => (data ? buildOption(data, view) : null), [data, view]);

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
                  "inline-flex h-6 w-6 items-center justify-center rounded-chip",
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
          <ErrorState message={error?.message} onRetry={() => void refetch()} />
        ) : option && data && data.points.length > 0 ? (
          <EChart option={option} ariaLabel="Forecast versus actual over time" />
        ) : (
          <EmptyState
            className="chart-box"
            icon={LineChart}
            title="Nothing to plot"
            message="No series falls inside the selected window — widen the forecast range."
          />
        )}
      </div>
    </Card>
  );
}
