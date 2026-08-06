"use client";

import { ArrowRight, BrainCircuit, CheckCircle2, Link2 } from "lucide-react";

import { ScoreLine } from "@/components/reports/scorecard";
import { Badge, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { useForecastMetrics, useSummary } from "@/hooks/use-dashboard";
import { formatCompact, humanizeModel } from "@/lib/format";
import { periodsAgo } from "@/lib/periods";
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

  const leading = data.leading_columns ?? [];
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
          <p className="text-meta font-semibold text-text-primary">
            How this forecast was made
          </p>
          <Badge tone="positive"><CheckCircle2 className="h-3 w-3" aria-hidden /> Best of {scored.length}</Badge>
        </div>
        {/*
          * A sentence rather than a row of acronyms. wMAPE and RMSE mean
          * nothing to the person this screen is for, and the two of them side
          * by side mostly prompt the question "which one do I look at?" —
          * they are still a click away for anyone who wants them.
          */}
        <p className="mt-0.5 text-caption text-text-muted">
          We tried {scored.length} method{scored.length === 1 ? "" : "s"} on your history and kept{" "}
          <span className="font-medium text-text-secondary">{humanizeModel(data.selected_model)}</span>
          {runnerUp ? `, which beat ${humanizeModel(runnerUp.model)}` : ""}
          {selected?.folds ? ` over ${selected.folds} test${selected.folds === 1 ? "" : "s"}` : ""}.
        </p>

        {/*
          * What the forecast looked at besides the target's own past. Worth a
          * line of its own: "we also read your web sessions" is the single
          * most reassuring thing this strip can say, and it only appears when
          * the column actually earned its place in the fit.
          */}
        {leading.length > 0 ? (
          <p className="mt-1 flex flex-wrap items-center gap-1.5 text-caption text-text-muted">
            <Link2 className="h-3 w-3 shrink-0 text-accent" aria-hidden />
            Also read{" "}
            {leading.map((column, index) => (
              <span key={column.name}>
                <span className="font-medium text-text-secondary">{column.name}</span>{" "}
                <span>from {periodsAgo(column.lag, data.frequency)}</span>
                {index < leading.length - 1 ? "," : ""}
              </span>
            ))}
          </p>
        ) : null}

        {/*
          * And how it actually did, once the periods it forecast had been
          * lived through — the backtest above is only what it would have done.
          */}
        <ScoreLine runId={runId} />
      </div>
      <dl className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <div title="How far off this method was when tested on periods it had not seen">
          <dt className="text-caption text-text-muted">Off by, on average</dt>
          <dd className="text-meta font-semibold text-text-primary num">
            {selected?.wmape == null ? "—" : `${selected.wmape.toFixed(1)}%`}
          </dd>
        </div>
        <div title="The size of a typical miss, in the units you are forecasting">
          <dt className="text-caption text-text-muted">Typical miss</dt>
          <dd className="text-meta font-semibold text-text-primary num">
            {selected?.rmse == null ? "—" : formatCompact(selected.rmse)}
          </dd>
        </div>
      </dl>
      <button
        type="button"
        onClick={() => openModal("model-detail")}
        className="inline-flex min-h-11 items-center gap-1.5 rounded-input px-2.5 text-meta font-medium text-accent transition-colors duration-fast hover:bg-accent-soft fine:min-h-8"
      >
        See the detail <ArrowRight className="h-3.5 w-3.5" aria-hidden />
      </button>
    </Card>
  );
}
