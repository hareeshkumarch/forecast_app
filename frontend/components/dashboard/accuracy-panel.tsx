"use client";

import { Gauge } from "lucide-react";
import { useMemo } from "react";

import { EChart, type ChartOption } from "@/components/charts/echart";
import { Badge, Card, ErrorState, PanelHeader, Skeleton } from "@/components/ui/primitives";
import { useAccuracyReport, useDecision, useForecastPoints, useSummary } from "@/hooks/use-dashboard";
import {
  type ChartPalette,
  axisLabel,
  axisLine,
  chartColors,
  splitLine,
  tooltipHeader,
  tooltipRow,
  tooltipStyle,
} from "@/lib/chart-theme";
import { humanizeModel } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useThemeRevision } from "@/stores/prefs-store";
import { periodWord } from "@/lib/periods";
import type {
  AccuracyReport,
  CoveragePoint,
  ForecastPointsResponse,
  HorizonAccuracy,
} from "@/types/api";

function accuracyOf(row: HorizonAccuracy): number | null {
  return row.wape == null ? null : Math.max(0, 100 - row.wape);
}

function buildOption(rows: HorizonAccuracy[], colors: ChartPalette): ChartOption {
  const labels = rows.map((row) => `+${row.horizon}`);
  const accuracy = rows.map(accuracyOf);
  const bias = rows.map((row) => row.bias_pct);
  const floor = Math.min(...accuracy.filter((value): value is number => value != null), 100);

  return {
    grid: { left: 4, right: 4, top: 26, bottom: 4, containLabel: true },
    tooltip: {
      trigger: "axis",
      ...tooltipStyle(colors),
      formatter: (params: unknown) => {
        const points = params as { dataIndex: number }[];
        const row = rows[points[0]?.dataIndex ?? 0];
        if (!row) return "";
        const measured = accuracyOf(row);
        return [
          tooltipHeader(`${row.horizon} period${row.horizon === 1 ? "" : "s"} ahead`, colors),
          tooltipRow(
            colors.accent,
            "Accuracy",
            measured == null ? "—" : `${measured.toFixed(1)}%`,
            colors,
          ),
          tooltipRow(
            colors.gold,
            "Bias",
            row.bias_pct == null ? "—" : `${row.bias_pct > 0 ? "+" : ""}${row.bias_pct.toFixed(1)}%`,
            colors,
          ),
          tooltipRow(colors.textMuted, "Scored on", `${row.observations}`, colors),
        ].join("");
      },
    },
    legend: {
      show: true,
      right: 0,
      top: 0,
      itemWidth: 10,
      itemHeight: 2,
      textStyle: axisLabel(colors),
      data: ["Accuracy", "Bias"],
    },
    xAxis: {
      type: "category",
      data: labels,
      axisLabel: axisLabel(colors),
      axisLine: axisLine(colors),
      axisTick: { show: false },
    },
    yAxis: [
      {
        type: "value",
        min: Math.max(0, Math.floor((floor - 8) / 10) * 10),
        max: 100,
        axisLabel: { ...axisLabel(colors), formatter: (value: number) => `${value}%` },
        splitLine: splitLine(colors),
      },
      {
        type: "value",
        axisLabel: {
          ...axisLabel(colors),
          formatter: (value: number) => `${value > 0 ? "+" : ""}${value}%`,
        },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: "Accuracy",
        type: "line",
        smooth: false,
        symbol: "circle",
        symbolSize: 5,
        data: accuracy,
        lineStyle: { width: 2, color: colors.accent },
        itemStyle: { color: colors.accent },
      },
      {
        name: "Bias",
        type: "bar",
        yAxisIndex: 1,
        barWidth: "36%",
        data: bias,
        itemStyle: { color: colors.gold, opacity: 0.55 },
      },
    ],
  };
}

function buildSpreadOption(
  data: ForecastPointsResponse,
  reliable: number | null,
  colors: ChartPalette,
): ChartOption {
  const ahead = data.points.slice(data.boundary_index ?? data.points.length);
  const rows = ahead.map((point, index) => {
    const width =
      point.lower_bound == null || point.upper_bound == null || !point.forecast
        ? null
        : ((point.upper_bound - point.lower_bound) / Math.abs(point.forecast)) * 100;
    return { step: index + 1, width };
  });

  return {
    grid: { left: 4, right: 4, top: 26, bottom: 4, containLabel: true },
    tooltip: {
      trigger: "axis",
      ...tooltipStyle(colors),
      formatter: (params: unknown) => {
        const points = params as { dataIndex: number }[];
        const row = rows[points[0]?.dataIndex ?? 0];
        if (!row) return "";
        return [
          tooltipHeader(`${row.step} period${row.step === 1 ? "" : "s"} ahead`, colors),
          tooltipRow(
            colors.accent,
            "Range width",
            row.width == null ? "—" : `${row.width.toFixed(0)}% of the forecast`,
            colors,
          ),
        ].join("");
      },
    },
    xAxis: {
      type: "category",
      data: rows.map((row) => `+${row.step}`),
      axisLabel: axisLabel(colors),
      axisLine: axisLine(colors),
      axisTick: { show: false },
    },
    yAxis: {
      type: "value",
      axisLabel: { ...axisLabel(colors), formatter: (value: number) => `${value}%` },
      splitLine: splitLine(colors),
    },
    series: [
      {
        name: "Range width",
        type: "bar",
        barWidth: "52%",
        data: rows.map((row) => ({
          value: row.width,
          itemStyle: {
            color: reliable != null && row.step > reliable ? colors.sand : colors.accent,
            opacity: reliable != null && row.step > reliable ? 0.55 : 1,
          },
        })),
        markLine:
          reliable == null || reliable >= rows.length
            ? undefined
            : {
                silent: true,
                symbol: "none",
                label: {
                  formatter: "planning stops here",
                  position: "insideEndTop",
                  ...axisLabel(colors),
                },
                lineStyle: { color: colors.borderStrong, type: "dashed", width: 1 },
                data: [{ xAxis: reliable - 0.5 }],
              },
      },
    ],
  };
}

export function AccuracyPanel({ className }: { className?: string } = {}) {
  const { data: summary } = useSummary();
  const runId = summary?.run_id ?? null;
  const { data, isLoading, isError, error, refetch } = useAccuracyReport(runId);
  const { data: points } = useForecastPoints(runId);
  const { data: decision } = useDecision();
  const revision = useThemeRevision();

  const rows = data?.by_horizon;
  const reliable = decision?.horizon?.periods ?? null;

  const option = useMemo(
    () =>
      rows?.length
        ? buildOption(rows, chartColors())
        : points
          ? buildSpreadOption(points, reliable, chartColors())
          : null,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [rows, points, reliable, revision],
  );

  if (!runId) return null;
  if (isLoading) return <Skeleton className={cn("h-72 w-full rounded-card", className)} />;
  if (isError) {
    return (
      <Card className={className}>
        <ErrorState error={error} onRetry={() => void refetch()} />
      </Card>
    );
  }
  if (!data) return null;

  const scored = Boolean(rows?.length);
  const word = points ? periodWord(points.frequency, reliable ?? 2) : "periods";

  return (
    <Card className={cn("flex min-w-0 flex-col", className)}>
      <PanelHeader
        title={scored ? "How accuracy holds up" : "How far ahead this holds"}
        subtitle={
          scored
            ? "Measured on periods that have since happened, by how far ahead they were"
            : `The range around each period, as a share of the number itself${
                reliable ? ` — firm for ${reliable} ${word}` : ""
              }`
        }
        actions={
          <Badge tone={data.measured_against_outcomes ? "positive" : "neutral"}>
            <Gauge className="h-3 w-3" aria-hidden />
            {data.measured_against_outcomes ? "Scored" : "Not yet scored"}
          </Badge>
        }
      />

      <div className="min-h-0 flex-1 px-3 pb-3">
        {option ? (
          <EChart
            option={option}
            ariaLabel={
              scored
                ? "Forecast accuracy and bias by how many periods ahead the forecast was made"
                : "How wide the forecast range grows with each period ahead"
            }
          />
        ) : null}

        <div className="mt-3 grid gap-3 border-t border-border pt-3 sm:grid-cols-2">
          <ValueAddLine report={data} />
          <CoverageLine report={data} />
        </div>

        {data.caveats.length > 0 ? (
          <ul className="mt-3 space-y-1 border-t border-border pt-3">
            {data.caveats.map((caveat) => (
              <li key={caveat} className="text-caption text-text-muted">
                {caveat}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </Card>
  );
}

function ValueAddLine({ report }: { report: AccuracyReport }) {
  const add = report.forecast_value_add;
  if (!add?.baseline || add.improvement_pct == null) return null;

  const better = add.beats_baseline;
  return (
    <div>
      <p className="text-caption text-text-muted">Against the simplest method</p>
      <p className="mt-0.5 text-meta text-text-primary">
        <span className={cn("font-semibold num", better ? "text-positive" : "text-negative")}>
          {better ? "−" : "+"}
          {Math.abs(add.improvement_pct).toFixed(1)}% error
        </span>{" "}
        versus {humanizeModel(add.baseline)}
        {better ? "" : " — the baseline was closer"}
      </p>
    </div>
  );
}

function CoverageLine({ report }: { report: AccuracyReport }) {
  const [first, ...rest] = report.coverage.filter((point) => point.measurable);
  if (!first) return null;

  const worst = rest.reduce<CoveragePoint>(
    (found, point) => (Math.abs(point.gap_pp) > Math.abs(found.gap_pp) ? point : found),
    first,
  );
  const measurable = [first, ...rest];
  const held = measurable.every((point) => point.holds);
  const nominal = Math.round(worst.nominal * 100);

  return (
    <div>
      <p className="text-caption text-text-muted">Did the range hold</p>
      <p className="mt-0.5 text-meta text-text-primary">
        <span className={cn("font-semibold num", held ? "text-positive" : "text-warning")}>
          {worst.observed.toFixed(0)}%
        </span>{" "}
        landed inside the {nominal}% range
        {held ? " — as promised" : `, ${Math.abs(worst.gap_pp).toFixed(0)}pp short at its worst`}
      </p>
    </div>
  );
}
