"use client";


import { PieChart } from "lucide-react";
import { useMemo } from "react";

import { EChart, type ChartOption } from "@/components/charts/echart";
import { Card, EmptyState, ErrorState, PanelHeader, Skeleton } from "@/components/ui/primitives";
import { useCategories } from "@/hooks/use-dashboard";
import {
  CATEGORICAL_PALETTE,
  CHART_COLORS,
  TOOLTIP_STYLE,
  tooltipHeader,
  tooltipRow,
} from "@/lib/chart-theme";
import { formatCompact, formatPercent } from "@/lib/format";
import type { CategoryResponse } from "@/types/api";

function buildOption(data: CategoryResponse): ChartOption {
  const rows = data.rows;

  return {
    backgroundColor: "transparent",
    animation: false,
    tooltip: {
      ...TOOLTIP_STYLE,
      trigger: "item",
      confine: true,
      formatter: (params: unknown) => {
        const point = params as { dataIndex: number };
        const row = rows[point.dataIndex];
        if (!row) return "";
        return (
          tooltipHeader(row.category) +
          tooltipRow(
            CATEGORICAL_PALETTE[point.dataIndex % CATEGORICAL_PALETTE.length] ?? CHART_COLORS.navy,
            "Forecast",
            formatCompact(row.forecast_value),
          ) +
          tooltipRow(CHART_COLORS.textMuted, "Share", formatPercent(row.share)) +
          (row.change_vs_last_year !== null
            ? tooltipRow(
                row.change_vs_last_year >= 0 ? CHART_COLORS.positive : CHART_COLORS.negative,
                "vs last year",
                `${row.change_vs_last_year >= 0 ? "+" : ""}${row.change_vs_last_year.toFixed(1)}%`,
              )
            : "")
        );
      },
    },
    series: [
      {
        type: "pie",
        
        radius: ["58%", "82%"],
        center: ["50%", "50%"],
        avoidLabelOverlap: false,
        label: { show: false },
        labelLine: { show: false },
        itemStyle: {
          borderColor: CHART_COLORS.surface,
          borderWidth: 2,
          borderRadius: 3,
        },
        emphasis: {
          scale: true,
          scaleSize: 3,
          itemStyle: { borderWidth: 2 },
        },
        data: rows.map((row, index) => ({
          name: row.category,
          value: Math.max(row.forecast_value, 0),
          itemStyle: {
            color: CATEGORICAL_PALETTE[index % CATEGORICAL_PALETTE.length] ?? CHART_COLORS.navy,
          },
        })),
      },
    ],
  };
}

export function ForecastByCategory() {
  const { data, isLoading, isError, error, refetch } = useCategories();
  const option = useMemo(() => (data ? buildOption(data) : null), [data]);

  return (
    <Card className="flex min-w-0 flex-col">
      <PanelHeader title="Forecast by Category" subtitle="Share of total forecast" />

      <div className="min-h-0 flex-1 px-3 pb-3">
        {isLoading ? (
          <div className="category-layout px-1 pt-2" aria-hidden>
            <Skeleton className="category-donut aspect-square rounded-full" />
            <div className="flex-1 space-y-2.5">
              {Array.from({ length: 5 }).map((_, index) => (
                <Skeleton key={index} className="h-4 w-full" />
              ))}
            </div>
          </div>
        ) : isError ? (
          <ErrorState message={error?.message} onRetry={() => void refetch()} />
        ) : option && data && data.rows.length > 0 ? (
          <div className="category-layout">
            
            <div className="category-donut relative">
              <EChart option={option} ariaLabel="Forecast split by product category" />
              <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
                <span className="text-micro font-semibold uppercase tracking-[0.09em] text-text-muted">
                  Total
                </span>
                <span className="mt-0.5 text-title font-semibold tracking-[-0.01em] text-text-primary num">
                  {data.total_display}
                </span>
              </div>
            </div>

            
            <ul className="min-w-0 flex-1 space-y-[7px]">
              {data.rows.map((row, index) => (
                <li key={row.category} className="flex items-center gap-2">
                  <span
                    className="h-2 w-2 shrink-0 rounded-[2px]"
                    style={{
                      background:
                        CATEGORICAL_PALETTE[index % CATEGORICAL_PALETTE.length] ??
                        CHART_COLORS.navy,
                    }}
                    aria-hidden
                  />
                  <span className="min-w-0 flex-1 truncate text-meta text-text-secondary">
                    {row.category}
                  </span>
                  <span className="shrink-0 text-meta font-medium text-text-muted num">
                    {formatPercent(row.share)}
                  </span>
                  <span className="w-[62px] shrink-0 text-right text-meta font-semibold text-text-primary num">
                    {formatCompact(row.forecast_value)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <EmptyState
            className="chart-box"
            icon={PieChart}
            title="No category breakdown"
            message="Map a category column when you run a forecast to split it by product."
          />
        )}
      </div>
    </Card>
  );
}
