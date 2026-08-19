"use client";

import { useMemo } from "react";

import { EChart, type ChartOption } from "@/components/charts/echart";
import {
  ROUTE_MARKS,
  axisLabel,
  axisLine,
  chartColors,
  splitLine,
  tooltipHeader,
  tooltipRow,
  tooltipStyle,
} from "@/lib/chart-theme";
import { formatCompact, formatPercent, humanizeModel } from "@/lib/format";
import { useThemeRevision } from "@/stores/prefs-store";
import type { SeriesRow } from "@/types/api";

const LABELLED = 5;
const MIN_SYMBOL = 7;
const MAX_SYMBOL = 26;
const MAX_LABEL_CHARS = 18;

type Point = {
  value: [number, number, number];
  row: SeriesRow;
  label?: { position: "left" | "right" };
};

/**
 * Fitted on its own history, or shared out from the level above it.
 *
 * The distinction the chart is for: error concentrated in fitted lines is a
 * modelling problem, and error concentrated in apportioned ones is a history
 * problem. They have different fixes, so they get different marks.
 */
function routeOf(row: SeriesRow): keyof typeof ROUTE_MARKS {
  return row.status === "forecast" && row.accuracy_measured ? "model" : "fallback";
}

export function AccuracyScatter({
  rows,
  currency = true,
  onSelect,
}: {
  rows: SeriesRow[];
  currency?: boolean;
  onSelect?: (row: SeriesRow) => void;
}) {
  const plotted = useMemo(
    () => rows.filter((row) => row.wmape !== null && row.forecast_total > 0),
    [rows],
  );

  const revision = useThemeRevision();
  const option = useMemo<ChartOption>(() => {
    const colors = chartColors();
    const risk = plotted.map((row) => Math.abs(row.value_at_risk ?? 0));
    const peak = Math.max(...risk, 1);

    // Area, not radius, carries the value at risk: doubling a radius quadruples
    // the ink and reads as four times the number.
    const size = (value: number) =>
      MIN_SYMBOL + (MAX_SYMBOL - MIN_SYMBOL) * Math.sqrt(Math.max(0, value) / peak);

    const worst = [...plotted]
      .sort((a, b) => Math.abs(b.value_at_risk ?? 0) - Math.abs(a.value_at_risk ?? 0))
      .slice(0, LABELLED)
      .map((row) => row.id);

    // The five labelled points are the five biggest, so they all sit at the
    // right-hand end and their labels ran off the plot on top of each other.
    // Anything past this line points its label back inwards.
    const inwards = Math.max(...plotted.map((row) => row.forecast_total)) / 12;

    const points = (route: keyof typeof ROUTE_MARKS): Point[] =>
      plotted
        .filter((row) => routeOf(row) === route)
        .map((row) => ({
          value: [row.forecast_total, row.wmape ?? 0, Math.abs(row.value_at_risk ?? 0)],
          row,
          label: { position: row.forecast_total >= inwards ? ("left" as const) : ("right" as const) },
        }));

    const series = (Object.keys(ROUTE_MARKS) as (keyof typeof ROUTE_MARKS)[]).map((route) => {
      const mark = ROUTE_MARKS[route];
      return {
        type: "scatter" as const,
        name: mark.label,
        symbol: mark.symbol,
        symbolSize: (point: unknown) => size((point as [number, number, number])[2]),
        data: points(route),
        itemStyle: {
          color: mark.hollow ? colors.surface : colors.accent,
          borderColor: colors.accent,
          // A ring in the surface colour keeps overlapping dots readable as
          // separate marks rather than as one darker blob.
          borderWidth: mark.hollow ? 1.5 : 1,
          opacity: mark.hollow ? 1 : 0.85,
        },
        emphasis: { itemStyle: { color: colors.accentHover, opacity: 1 } },
        labelLayout: { hideOverlap: true, moveOverlap: "shiftY" as const },
        label: {
          show: true,
          position: "right" as const,
          distance: 6,
          fontSize: 10,
          color: colors.textSecondary,
          formatter: (params: unknown) => {
            const { data } = params as { data: Point };
            if (!worst.includes(data.row.id)) return "";
            const label = data.row.label;
            return label.length > MAX_LABEL_CHARS
              ? `${label.slice(0, MAX_LABEL_CHARS - 1)}…`
              : label;
          },
        },
      };
    });

    return {
      grid: { left: 8, right: 40, top: 28, bottom: 8, containLabel: true },
      legend: {
        top: 0,
        right: 0,
        itemGap: 14,
        icon: "circle",
        textStyle: { ...axisLabel(colors), color: colors.textSecondary },
      },
      tooltip: {
        ...tooltipStyle(colors),
        formatter: (params: unknown) => {
          const { data } = params as { data: Point };
          const { row } = data;
          return [
            tooltipHeader(row.label, colors),
            tooltipRow(colors.accent, "Forecast", formatCompact(row.forecast_total, currency), colors),
            tooltipRow(colors.textSecondary, "Error (wMAPE)", formatPercent(row.wmape ?? 0), colors),
            tooltipRow(
              colors.textSecondary,
              "Value at risk",
              formatCompact(Math.abs(row.value_at_risk ?? 0), currency),
              colors,
            ),
            tooltipRow(
              colors.textMuted,
              ROUTE_MARKS[routeOf(row)].label,
              row.model ? humanizeModel(row.model) : "not fitted",
              colors,
            ),
          ].join("");
        },
      },
      xAxis: {
        type: "log",
        name: "Forecast size",
        nameLocation: "middle" as const,
        nameGap: 26,
        nameTextStyle: { ...axisLabel(colors), color: colors.textSecondary },
        axisLabel: { ...axisLabel(colors), formatter: (v: number) => formatCompact(v, currency) },
        axisLine: axisLine(colors),
        splitLine: splitLine(colors),
      },
      yAxis: {
        type: "value",
        name: "Error",
        nameLocation: "middle" as const,
        nameGap: 38,
        nameTextStyle: { ...axisLabel(colors), color: colors.textSecondary },
        axisLabel: { ...axisLabel(colors), formatter: (v: number) => `${v}%` },
        axisLine: { show: false },
        splitLine: splitLine(colors),
      },
      series,
    } satisfies ChartOption;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plotted, currency, revision]);

  if (plotted.length === 0) return null;

  return (
    <div className="h-[300px]">
      <EChart
        option={option}
        fill
        ariaLabel={`Error against forecast size for ${plotted.length} series. Filled circles were fitted on their own history, hollow diamonds were estimated from the level above. Dot area is value at risk.`}
        onEvents={
          onSelect
            ? {
                click: (params: { data?: Point }) => {
                  if (params.data?.row) onSelect(params.data.row);
                },
              }
            : undefined
        }
      />
    </div>
  );
}
