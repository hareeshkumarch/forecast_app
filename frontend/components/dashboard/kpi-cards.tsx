"use client";


import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Gauge,
  Target,
  TrendingDown,
  TrendingUp,
  Wallet,
  type LucideIcon,
} from "lucide-react";

import { Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { useSummary } from "@/hooks/use-dashboard";
import { cn } from "@/lib/utils";
import type { KpiCard as KpiCardModel } from "@/types/api";


const KPI_ICONS: Record<string, LucideIcon> = {
  total_forecast: Wallet,
  actual_ytd: Activity,
  forecast_accuracy: Target,
  weighted_mape: Gauge,
  best_case: TrendingUp,
  worst_case: TrendingDown,
};

const TONE_TEXT = {
  positive: "text-positive",
  negative: "text-negative",
  neutral: "text-text-muted",
} as const;

const TONE_BG = {
  positive: "bg-positive-soft",
  negative: "bg-negative-soft",
  neutral: "bg-surface-muted",
} as const;

export function KpiCards() {
  const { data, isLoading, isError, error, refetch } = useSummary();

  if (isLoading) {
    return (
      <div className="grid grid-cols-6 gap-3">
        {Array.from({ length: 6 }).map((_, index) => (
          <Card key={index} className="p-3">
            <Skeleton className="h-6 w-6 rounded-[7px]" />
            <Skeleton className="mt-2.5 h-3 w-20" />
            <Skeleton className="mt-2 h-6 w-24" />
            <Skeleton className="mt-2 h-3 w-16" />
          </Card>
        ))}
      </div>
    );
  }

  if (isError) {
    return (
      <Card>
        <ErrorState message={error?.message} onRetry={() => void refetch()} />
      </Card>
    );
  }

  if (!data?.has_data || data.kpis.length === 0) {
    return (
      <Card className="px-4 py-6">
        <p className="text-body font-medium text-text-primary">No forecast yet</p>
        <p className="mt-1 text-caption text-text-muted">
          Upload a dataset and run a forecast to populate these metrics.
        </p>
      </Card>
    );
  }

  return (
    <div className="grid grid-cols-6 gap-3">
      {data.kpis.map((kpi) => (
        <KpiTile key={kpi.key} kpi={kpi} />
      ))}
    </div>
  );
}

function KpiTile({ kpi }: { kpi: KpiCardModel }) {
  const Icon = KPI_ICONS[kpi.key] ?? Activity;
  const Arrow = kpi.direction === "up" ? ArrowUpRight : ArrowDownRight;

  return (
    <Card className="flex flex-col p-2.5">
      <span
        className={cn(
          "flex h-6 w-6 items-center justify-center rounded-[7px] border border-border",
          TONE_BG[kpi.tone],
        )}
        aria-hidden
      >
        <Icon className={cn("h-3.5 w-3.5", TONE_TEXT[kpi.tone])} />
      </span>

      <p className="mt-2 truncate text-caption font-medium text-text-secondary">{kpi.label}</p>

      <p className="mt-1 text-kpi font-semibold tracking-[-0.02em] text-text-primary num">
        {kpi.display_value}
      </p>

      
      <div className="mt-1.5 space-y-0.5">
        {kpi.delta_display && kpi.direction !== "flat" ? (
          <span
            className={cn(
              "inline-flex items-center gap-0.5 rounded-chip border px-1 py-px text-caption font-medium",
              kpi.tone === "positive"
                ? "border-[#cfe6d9] bg-positive-soft text-positive"
                : kpi.tone === "negative"
                  ? "border-[#f0cdcc] bg-negative-soft text-negative"
                  : "border-border bg-surface-muted text-text-secondary",
            )}
          >
            <Arrow className="h-2.5 w-2.5" aria-hidden />
            {kpi.delta_display}
          </span>
        ) : null}
        {kpi.comparison_label ? (
          <span
            className="block truncate text-caption text-text-muted"
            title={kpi.comparison_label}
          >
            {kpi.comparison_label}
          </span>
        ) : null}
      </div>
    </Card>
  );
}
