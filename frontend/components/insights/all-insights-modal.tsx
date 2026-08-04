"use client";


import { useState } from "react";

import { InsightCard } from "@/components/insights/insights-rail";
import { Modal } from "@/components/ui/modal";
import { ErrorState } from "@/components/ui/primitives";
import { useInsights } from "@/hooks/use-dashboard";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { InsightSeverity } from "@/types/api";

const FILTERS: { value: InsightSeverity | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "critical", label: "Critical" },
  { value: "warning", label: "Warning" },
  { value: "positive", label: "Positive" },
  { value: "info", label: "Info" },
];

/**
 * "View All Insights" used to open whichever insight happened to be first.
 * This is the list it promised, with the rail's cards reused verbatim.
 */
export function AllInsightsModal() {
  const modal = useUiStore((state) => state.modal);
  const closeModal = useUiStore((state) => state.closeModal);
  const openInsight = useUiStore((state) => state.openInsight);
  const open = modal === "all-insights";

  const { data, isError, error, refetch } = useInsights();
  const [filter, setFilter] = useState<InsightSeverity | "all">("all");

  const items = data?.items ?? [];
  const visible = filter === "all" ? items : items.filter((item) => item.severity === filter);

  return (
    <Modal
      open={open}
      onClose={closeModal}
      title="AI Insights"
      description={`${items.length} generated from the current run`}
      size="lg"
    >
      {isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-1.5">
            {FILTERS.map((option) => {
              const count =
                option.value === "all"
                  ? items.length
                  : items.filter((item) => item.severity === option.value).length;

              return (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => setFilter(option.value)}
                  disabled={count === 0 && option.value !== "all"}
                  className={cn(
                    "rounded-chip border px-2 py-1 text-caption font-medium transition-colors duration-fast",
                    filter === option.value
                      ? "border-accent-border bg-accent-soft text-accent"
                      : "border-border bg-surface text-text-secondary hover:bg-surface-muted",
                    "disabled:cursor-not-allowed disabled:text-text-muted disabled:hover:bg-surface",
                  )}
                >
                  {option.label}
                  <span className="ml-1 num">{count}</span>
                </button>
              );
            })}
          </div>

          {visible.length === 0 ? (
            <p className="py-6 text-center text-caption text-text-muted">
              No insights in this category.
            </p>
          ) : (
            <div className="grid gap-2.5 sm:grid-cols-2">
              {visible.map((insight) => (
                <InsightCard
                  key={insight.id}
                  insight={insight}
                  onOpen={() => {

                    closeModal();
                    openInsight(insight);
                  }}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
