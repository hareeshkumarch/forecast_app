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

/**
 * What the forecast got wrong, period by period, against a zero line.
 *
 * The sign is carried by which side of the baseline a bar sits on, and not by
 * its colour. That is not a stylistic preference: the brand's warm and cool
 * steps separate by ΔE 3.3 under protanopia and 8.8 for normal vision against
 * a floor of 15, so a reader who cannot tell gold from teal would have had no
 * way to read over-forecast from under. Position is free of all of that.
 *
 * The band is one standard deviation of these residuals. It is the reference
 * that turns a wall of bars into a reading: inside it is the ordinary scatter
 * of a working model, and the bars that clear it are the periods worth
 * opening.
 */
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
                  // Opaque: `surfaceMuted` is already the quietest fill the
                  // system has, and putting it at half strength on top of
                  // `surface` left a band nobody could see — which is a
                  // reference line that is not there.
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
