"use client";


import { Check, X } from "lucide-react";

import { Modal } from "@/components/ui/modal";
import { Badge, ErrorState, Skeleton } from "@/components/ui/primitives";
import { useForecastMetrics, useSummary } from "@/hooks/use-dashboard";
import { formatCompact, formatMetric, humanizeKey, humanizeModel } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";
import type { ModelCandidate } from "@/types/api";

function formatScore(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return value.toFixed(3);
}

/**
 * Backs the "Model: …" chip in the workspace header. The run already reports
 * every candidate it backtested — this is where that comparison lives.
 */
export function ModelDetailModal() {
  const modal = useUiStore((state) => state.modal);
  const closeModal = useUiStore((state) => state.closeModal);
  const open = modal === "model-detail";

  const { data: summary } = useSummary();
  const runId = summary?.run_id ?? null;
  const { data, isLoading, isError, error, refetch } = useForecastMetrics(open ? runId : null);

  return (
    <Modal
      open={open}
      onClose={closeModal}
      title="Model selection"
      description={summary?.run_name ?? undefined}
      size="lg"
    >
      {isLoading ? (
        <div className="space-y-3" aria-hidden>
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      ) : isError ? (
        <ErrorState error={error} onRetry={() => void refetch()} />
      ) : !data ? (
        <p className="text-caption text-text-muted">
          Run a forecast to see how its model was chosen.
        </p>
      ) : (
        <div className="space-y-4">
          <div className="rounded-card border border-accent-border bg-accent-soft px-3 py-2.5">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="accent">{humanizeModel(data.selected_model)}</Badge>
              <span className="text-caption text-text-muted">Scored by {data.scoring_rule}</span>
            </div>
            {data.selection_rationale ? (
              <p className="mt-1.5 text-caption leading-[16px] text-text-primary">
                {data.selection_rationale}
              </p>
            ) : null}
          </div>

          {data.metrics.length > 0 ? (
            <section>
              <h3 className="eyebrow">Accuracy of the selected model</h3>
              <dl className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
                {data.metrics.map((metric) => (
                  <div
                    key={metric.name}
                    className="rounded-card border border-border bg-surface-muted px-2.5 py-2"
                  >
                    <dt className="truncate text-caption text-text-muted" title={humanizeKey(metric.name)}>
                      {humanizeKey(metric.name)}
                    </dt>
                    <dd className="mt-0.5 text-subhead font-semibold text-text-primary num">
                      {formatMetric(metric.value, metric.unit)}
                    </dd>
                  </div>
                ))}
              </dl>
            </section>
          ) : null}

          <section>
            <h3 className="eyebrow">Candidates</h3>
            <div className="scroll-thin mt-2 overflow-x-auto rounded-card border border-border">
              <table className="w-full min-w-[520px] border-collapse">
                <thead>
                  <tr className="border-b border-border bg-surface-muted">
                    <th className="table-header px-3 py-1.5 text-left font-medium">Model</th>
                    <th className="table-header px-3 py-1.5 text-right font-medium">wMAPE</th>
                    <th className="table-header px-3 py-1.5 text-right font-medium">sMAPE</th>
                    <th className="table-header px-3 py-1.5 text-right font-medium">RMSE</th>
                    <th className="table-header px-3 py-1.5 text-right font-medium">Score</th>
                    <th className="table-header px-3 py-1.5 text-right font-medium">Folds</th>
                  </tr>
                </thead>
                <tbody>
                  {data.candidates.map((candidate) => (
                    <CandidateRow key={candidate.id} candidate={candidate} />
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-1.5 text-caption text-text-muted">
              Lower is better for every column. The winner is the lowest weighted score across
              backtest folds.
            </p>
          </section>
        </div>
      )}
    </Modal>
  );
}

function CandidateRow({ candidate }: { candidate: ModelCandidate }) {
  return (
    <tr
      className={cn(
        "border-b border-border last:border-0",
        candidate.selected && "bg-accent-soft/50",
      )}
    >
      <td className="px-3 py-2 text-meta text-text-primary">
        <span className="flex items-center gap-1.5">
          {candidate.selected ? (
            <Check className="h-3.5 w-3.5 shrink-0 text-accent" aria-label="selected" />
          ) : candidate.failed ? (
            <X className="h-3.5 w-3.5 shrink-0 text-negative" aria-label="failed" />
          ) : (
            <span className="w-3.5" aria-hidden />
          )}
          <span className={cn("truncate", candidate.selected && "font-semibold")}>
            {humanizeModel(candidate.model)}
          </span>
        </span>
        {candidate.failed && candidate.failure_reason ? (
          <span className="mt-0.5 block pl-5 text-caption text-text-muted">
            {candidate.failure_reason}
          </span>
        ) : null}
      </td>
      <td className="px-3 py-2 text-right text-meta text-text-secondary num">
        {candidate.wmape === null ? "—" : `${candidate.wmape.toFixed(1)}%`}
      </td>
      <td className="px-3 py-2 text-right text-meta text-text-secondary num">
        {candidate.smape === null ? "—" : `${candidate.smape.toFixed(1)}%`}
      </td>
      <td className="px-3 py-2 text-right text-meta text-text-secondary num">
    {candidate.rmse === null ? "—" : formatCompact(candidate.rmse)}
      </td>
      <td className="px-3 py-2 text-right text-meta font-medium text-text-primary num">
        {formatScore(candidate.score)}
      </td>
      <td className="px-3 py-2 text-right text-meta text-text-muted num">{candidate.folds}</td>
    </tr>
  );
}
