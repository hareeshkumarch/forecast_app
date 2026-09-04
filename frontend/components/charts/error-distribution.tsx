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
import type { ResidualBucket } from "@/types/api";

/**
 * The shape of the error, bucketed symmetrically about zero.
 *
 * Centred on zero rather than on the data's own range, because the question
 * is whether the misses are balanced — and a range that starts at the
 * smallest residual puts the middle wherever the data happens to sit, which
 * hides exactly the lean the reader came for.
 *
 * A tall middle and short tails is a model that is working. Weight piled on
 * one side is a forecast that leans, which a planner can correct. The same
 * spread with nothing in the middle is neither, and is the one worth opening
 * the periods for.
 */
export function ErrorDistribution({
  buckets,
  currency = true,
}: {
  buckets: ResidualBucket[];
  currency?: boolean;
}) {
  const revision = useThemeRevision();

  const option = useMemo<ChartOption>(() => {
    const colors = chartColors();
    const centres = buckets.map((bucket) => (bucket.start + bucket.end) / 2);

    return {
      grid: { left: 8, right: 12, top: 16, bottom: 8, containLabel: true },
      xAxis: {
        type: "category",
        data: centres.map((value) => formatCompact(value, currency)),
        axisLabel: { ...axisLabel(colors), hideOverlap: true },
        axisLine: axisLine(colors),
        axisTick: { show: false },
        name: "Forecast minus actual",
        nameLocation: "middle",
        nameGap: 26,
        nameTextStyle: { ...axisLabel(colors), fontSize: 10 },
      },
      yAxis: {
        type: "value",
        minInterval: 1,
        splitLine: splitLine(colors),
        axisLabel: axisLabel(colors),
      },
      tooltip: {
        trigger: "item",
        ...tooltipStyle(colors),
        formatter: (params: unknown) => {
          const entry = params as { dataIndex: number };
          const bucket = buckets[entry.dataIndex];
          if (!bucket) return "";
          const span = `${formatCompact(bucket.start, currency)} to ${formatCompact(bucket.end, currency)}`;
          return [
            tooltipHeader(span, colors),
            tooltipRow(
              colors.accent,
              bucket.count === 1 ? "period" : "periods",
              String(bucket.count),
              colors,
            ),
          ].join("");
        },
      },
      series: [
        {
          type: "bar",
          name: "Periods",
          data: buckets.map((bucket) => bucket.count),
          itemStyle: { color: colors.accent, borderRadius: 2 },
          // A surface gap between neighbours, so two full buckets read as two
          // rather than as one wide block.
          barCategoryGap: "12%",
          markLine: {
            silent: true,
            symbol: "none",
            label: { show: false },
            lineStyle: { color: colors.borderStrong, width: 1 },
            data: [{ xAxis: (buckets.length - 1) / 2 }],
          },
        },
      ],
    } satisfies ChartOption;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [buckets, currency, revision]);

  return (
    <EChart
      option={option}
      ariaLabel="How many periods fall into each band of forecast error, centred on zero"
    />
  );
}
