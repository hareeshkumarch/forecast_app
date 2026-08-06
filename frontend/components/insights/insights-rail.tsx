"use client";

import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  AlertTriangle,
  ArrowUpRight,
  Flame,
  Lightbulb,
  MoreHorizontal,
  ShieldAlert,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Waves,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";

import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  MENU_CONTENT,
  MENU_ITEM,
  Skeleton,
} from "@/components/ui/primitives";
import { ProviderLogo } from "@/components/ui/provider-logo";
import { usePlainInsights, useInsights, useRewriteInsights } from "@/hooks/use-dashboard";
import { formatMetric } from "@/lib/format";
import { PROVIDERS, loadLlmConfig } from "@/lib/llm-config";
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

function useConfiguredProvider(): { id: string; label: string } | null {
  const [provider, setProvider] = useState<{ id: string; label: string } | null>(null);

  useEffect(() => {
    const config = loadLlmConfig();
    if (!config.apiKey.trim()) return;
    const known = PROVIDERS.find((entry) => entry.value === config.provider);
    setProvider({ id: config.provider, label: known?.label ?? config.provider });
  }, []);

  return provider;
}

export function InsightsRailBody() {
  const { data, isLoading, isError, error, refetch } = useInsights();
  const openInsight = useUiStore((state) => state.openInsight);
  const openModal = useUiStore((state) => state.openModal);
  const provider = useConfiguredProvider();
  const rewrite = useRewriteInsights();
  const plain = usePlainInsights();

  const items = data?.items ?? [];
  const rewritten = items.filter((insight) => insight.llm_rewritten).length;
  const busy = rewrite.isPending || plain.isPending;

  return (
    <>
      <div className="px-4 pb-2 pt-4">
        <div className="flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 text-accent" aria-hidden />
          <h2 className="text-subhead font-semibold text-text-primary">Forecast Insights</h2>
          {items.length > 0 ? (
            <span className="ml-auto text-caption text-text-muted num">{items.length}</span>
          ) : null}

          <DropdownMenu.Root>
            <DropdownMenu.Trigger asChild>
              <button
                type="button"
                aria-label="Insight wording"
                disabled={items.length === 0}
                className={cn(
                  "inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-chip",
                  "text-text-muted transition-colors duration-fast",
                  "hover:bg-surface-muted hover:text-text-primary",
                  "disabled:pointer-events-none disabled:opacity-40",
                  items.length === 0 ? "" : "ml-0.5",
                )}
              >
                <MoreHorizontal className="h-4 w-4" aria-hidden />
              </button>
            </DropdownMenu.Trigger>
            <DropdownMenu.Portal>
              <DropdownMenu.Content align="end" sideOffset={4} className={MENU_CONTENT}>
                <DropdownMenu.Item
                  disabled={!provider || busy}
                  onSelect={() => rewrite.mutate()}
                  className={MENU_ITEM}
                >
                  {provider ? (
                    <ProviderLogo provider={provider.id} className="h-3.5 w-3.5" />
                  ) : null}
                  {provider ? `Reword with ${provider.label}` : "Reword with AI"}
                </DropdownMenu.Item>
                <DropdownMenu.Item
                  disabled={rewritten === 0 || busy}
                  onSelect={() => plain.mutate()}
                  className={MENU_ITEM}
                >
                  Use the plain wording
                </DropdownMenu.Item>
                <DropdownMenu.Separator className="my-1 h-px bg-border" />
                <DropdownMenu.Item onSelect={() => openModal("settings")} className={MENU_ITEM}>
                  Choose a provider…
                </DropdownMenu.Item>
              </DropdownMenu.Content>
            </DropdownMenu.Portal>
          </DropdownMenu.Root>
        </div>

        {items.length > 0 ? (
          <p className="mt-1 flex items-center gap-1.5 text-caption text-text-muted">
            {rewritten > 0 && provider ? (
              <>
                <ProviderLogo provider={provider.id} className="h-3 w-3" />
                <span>Worded by {provider.label}. The figures are the platform&apos;s.</span>
              </>
            ) : (
              <span>
                Written by the platform.
                {provider ? "" : " Add a provider in Settings to have them reworded."}
              </span>
            )}
          </p>
        ) : null}

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
