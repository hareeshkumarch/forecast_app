"use client";


import {
  AlertTriangle,
  ArrowUpRight,
  Flame,
  Lightbulb,
  ShieldAlert,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Waves,
  type LucideIcon,
} from "lucide-react";

import { Badge, Button, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { useInsights } from "@/hooks/use-dashboard";
import { formatMetric } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { Insight, InsightSeverity, InsightType } from "@/types/api";

const TYPE_ICONS: Record<InsightType, LucideIcon> = {
  accuracy_change: TrendingUp,
  forecast_gap: Flame,
  regional_growth: ArrowUpRight,
  category_decline: TrendingDown,
  anomaly: AlertTriangle,
  confidence_widening: Waves,
  worst_case_risk: ShieldAlert,
  driver_positive: TrendingUp,
  driver_negative: TrendingDown,
  recommendation: Lightbulb,
};

const SEVERITY_STYLES: Record<
  InsightSeverity,
  { border: string; iconBg: string; iconText: string; title: string }
> = {
  positive: {
    border: "border-positive-border",
    iconBg: "bg-positive-soft",
    iconText: "text-positive",
    title: "text-positive",
  },
  info: {
    border: "border-border",
    iconBg: "bg-surface-muted",
    iconText: "text-text-secondary",
    title: "text-text-primary",
  },
  warning: {
    border: "border-warning-border",
    iconBg: "bg-warning-soft",
    iconText: "text-warning",
    title: "text-warning",
  },
  critical: {
    border: "border-negative-border",
    iconBg: "bg-negative-soft",
    iconText: "text-negative",
    title: "text-negative",
  },
};

/**
 * Fixed sidebar from `2xl` up. It is the first thing to go when space runs
 * short: below that width the 320px it wants costs the workspace its
 * side-by-side charts, and the same cards are one tap away in the header.
 */
export function InsightsRail() {
  return (
    <aside
   aria-label="Forecast insights"
   className="hidden w-insights shrink-0 flex-col border-l border-border bg-surface min-[1720px]:flex"
    >
      <InsightsRailBody />
    </aside>
  );
}

export function InsightsRailBody() {
  const { data, isLoading, isError, error, refetch } = useInsights();
  const openInsight = useUiStore((state) => state.openInsight);
  const openModal = useUiStore((state) => state.openModal);

  const items = data?.items ?? [];

  return (
    <>
      <div className="px-4 pb-2 pt-4">
        <div className="flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden />
     <h2 className="text-subhead font-semibold text-text-primary">Forecast Insights</h2>
          {items.length > 0 ? (
            <span className="ml-auto text-caption text-text-muted num">{items.length}</span>
          ) : null}
        </div>

        <div className="mt-2.5 h-px w-full bg-gradient-to-r from-accent/45 to-transparent" />
      </div>

      <div className="scroll-thin min-h-0 flex-1 space-y-2.5 overflow-y-auto px-3 pb-3">
        {isLoading ? (
          Array.from({ length: 5 }).map((_, index) => (
            <div key={index} className="rounded-card border border-border p-3" aria-hidden>
              <Skeleton className="h-3.5 w-32" />
              <Skeleton className="mt-2 h-3 w-full" />
              <Skeleton className="mt-1.5 h-3 w-4/5" />
              <Skeleton className="mt-2.5 h-3 w-20" />
            </div>
          ))
        ) : isError ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : items.length === 0 ? (
          <EmptyState
            className="rounded-card border border-dashed border-border"
            icon={Sparkles}
            title="No insights yet"
            message="Insights are derived from a completed forecast run."
          />
        ) : (
          items.map((insight) => (
            <InsightCard key={insight.id} insight={insight} onOpen={() => openInsight(insight)} />
          ))
        )}
      </div>

      <div className="border-t border-border p-3">
        <Button
          variant="secondary"
          size="md"
          className="w-full"
          disabled={items.length === 0}
          onClick={() => openModal("all-insights")}
        >
          View All Insights
        </Button>
      </div>
    </>
  );
}

export function InsightCard({ insight, onOpen }: { insight: Insight; onOpen: () => void }) {
  const Icon = TYPE_ICONS[insight.type] ?? Sparkles;
  const style = SEVERITY_STYLES[insight.severity];

  return (
    <article className={cn("rounded-card border bg-surface p-3", style.border)}>
      <div className="flex items-start gap-2">
        <span
          className={cn(
            "mt-px flex h-5 w-5 shrink-0 items-center justify-center rounded-[6px]",
            style.iconBg,
          )}
          aria-hidden
        >
          <Icon className={cn("h-3 w-3", style.iconText)} />
        </span>
        <h3 className={cn("text-body font-semibold leading-[17px]", style.title)}>
          {insight.title}
        </h3>
      </div>


      <p className="mt-1.5 line-clamp-3 text-caption leading-[16px] text-text-secondary">
        {insight.explanation}
      </p>

   <div className="mt-2.5 flex items-center justify-between gap-2">
        <span className="truncate text-caption font-medium text-text-muted num">
          {formatMetric(insight.metric_value, insight.metric_unit)}
        </span>
    <button
          type="button"
          onClick={onOpen}
          className="shrink-0 text-caption font-medium text-accent transition-colors duration-fast hover:text-accent-hover"
        >
     View Details →
    </button>
   </div>
   {insight.llm_rewritten ? <Badge tone="accent" className="mt-2">LLM enhanced</Badge> : null}
  </article>
  );
}
