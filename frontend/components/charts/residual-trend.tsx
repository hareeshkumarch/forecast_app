"use client";

import { useMemo } from "react";

import { EChart, type ChartOption } from "@/components/charts/echart";
import {
  axisLabel,
  axisLine,
  chartColors,
  splitLine,
  tooltipHeader,
  tooltipRow,
  tooltipStyle,
} from "@/lib/chart-theme";
import { formatCompact } from "@/lib/format";
import { useThemeRevision } from "@/stores/prefs-store";
import type { Residual } from "@/types/api";

export function ResidualTrend({
  residuals,
  sigma,
  currency = true,
}: {
  residuals: Residual[];
  sigma: number | null;
  currency?: boolean;
}) {
  const revision = useThemeRevision();

  const option = useMemo<ChartOption>(() => {
    const colors = chartColors();
    const band = sigma && Number.isFinite(sigma) && sigma > 0 ? sigma : null;

    return {
      grid: { left: 8, right: 12, top: 16, bottom: 8, containLabel: true },
      xAxis: {
        type: "category",
        data: residuals.map((row) => row.period),
        axisLabel: { ...axisLabel(colors), hideOverlap: true },
        axisLine: axisLine(colors),
        axisTick: { show: false },
      },
      yAxis: {
        type: "value",
        splitLine: splitLine(colors),
        axisLabel: { ...axisLabel(colors), formatter: (v: number) => formatCompact(v, currency) },
      },
      tooltip: {
        trigger: "axis",
        ...tooltipStyle(colors),
        formatter: (params: unknown) => {
          const entries = params as { dataIndex: number }[];
          const row = residuals[entries?.[0]?.dataIndex ?? 0];
          if (!row) return "";
          const leaning = row.residual >= 0 ? "Over by" : "Under by";
          return [
            tooltipHeader(row.period, colors),
            tooltipRow(colors.textMuted, "Actual", formatCompact(row.actual, currency), colors),
            tooltipRow(colors.accent, "Forecast", formatCompact(row.predicted, currency), colors),
            tooltipRow(
              colors.textPrimary,
              leaning,
              formatCompact(Math.abs(row.residual), currency),
              colors,
            ),
          ].join("");
        },
      },
      series: [
        {
          type: "bar",
          name: "Residual",
          data: residuals.map((row) => row.residual),
          itemStyle: { color: colors.accent, borderRadius: 2 },
          barMaxWidth: 14,
          markLine: {
            silent: true,
            symbol: "none",
            label: { show: false },
            lineStyle: { color: colors.borderStrong, width: 1, type: "solid" },
            data: [{ yAxis: 0 }],
          },
          ...(band
            ? {
                markArea: {
                  silent: true,
                  itemStyle: { color: colors.surfaceMuted },
                  data: [[{ yAxis: -band }, { yAxis: band }]],
                },
              }
            : {}),
        },
      ],
    } satisfies ChartOption;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [residuals, sigma, currency, revision]);

  return (
    <EChart
      option={option}
      ariaLabel="Forecast error for each period, above or below a zero line, with a one-standard-deviation band"
    />
  );
}
