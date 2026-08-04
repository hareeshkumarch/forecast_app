"use client";

import { ArrowRight, BrainCircuit, CheckCircle2 } from "lucide-react";

import { Badge, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { useForecastMetrics, useSummary } from "@/hooks/use-dashboard";
import { formatCompact, humanizeModel } from "@/lib/format";
import { useUiStore } from "@/stores/ui-store";

export function ModelHealthStrip() {
  const { data: summary } = useSummary();
  const openModal = useUiStore((state) => state.openModal);
  const runId = summary?.run_id ?? null;
  const { data, isLoading, isError, error, refetch } = useForecastMetrics(runId);

  if (!runId) return null;
  if (isLoading) return <Skeleton className="mt-3 h-20 w-full" />;
  if (isError) return <Card className="mt-3"><ErrorState error={error} onRetry={() => void refetch()} className="py-4" /></Card>;
  if (!data) return null;

  const selected = data.candidates.find((candidate) => candidate.selected);
  const scored = data.candidates.filter((candidate) => !candidate.failed);
  const runnerUp = scored.find((candidate) => !candidate.selected);

  return (
    <Card className="mt-3 flex flex-wrap items-center gap-3 px-4 py-3">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-input bg-accent-soft">
        <BrainCircuit className="h-4 w-4 text-accent" aria-hidden />
      </span>
      <div className="min-w-[190px] flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-meta font-semibold text-text-primary">Model health</p>
          <Badge tone="positive"><CheckCircle2 className="h-3 w-3" aria-hidden /> Selected</Badge>
        </div>
        <p className="mt-0.5 text-caption text-text-muted">
          {humanizeModel(data.selected_model)} won across {selected?.folds ?? 0} folds
          {runnerUp ? ` ahead of ${humanizeModel(runnerUp.model)}` : ""}.
        </p>
      </div>
      <dl className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <div><dt className="text-caption text-text-muted">wMAPE</dt><dd className="text-meta font-semibold text-text-primary num">{selected?.wmape == null ? "—" : `${selected.wmape.toFixed(1)}%`}</dd></div>
        <div><dt className="text-caption text-text-muted">RMSE</dt><dd className="text-meta font-semibold text-text-primary num">{selected?.rmse == null ? "—" : formatCompact(selected.rmse)}</dd></div>
        <div><dt className="text-caption text-text-muted">Candidates</dt><dd className="text-meta font-semibold text-text-primary num">{scored.length}/{data.candidates.length}</dd></div>
      </dl>
      <button
        type="button"
        onClick={() => openModal("model-detail")}
        className="inline-flex min-h-11 items-center gap-1.5 rounded-input px-2.5 text-meta font-medium text-accent transition-colors duration-fast hover:bg-accent-soft sm:min-h-8"
      >
        Open model lab <ArrowRight className="h-3.5 w-3.5" aria-hidden />
      </button>
    </Card>
  );
}
