"use client";

import { Activity, Download, Eye, FileBarChart2, FileText, Plus, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";

import { Scorecard } from "@/components/reports/scorecard";
import { RefreshButton } from "@/components/ui/refresh-button";
import { Badge, Button, Card, EmptyState, ErrorState, Skeleton } from "@/components/ui/primitives";
import { downloadExport, useDeleteForecastRun, useForecastRuns } from "@/hooks/use-dashboard";
import { formatRelativeTime, humanizeModel } from "@/lib/format";
import { useUiStore } from "@/stores/ui-store";
import type { ForecastRun, MeasureAggregation, RunStatus } from "@/types/api";

const STATUS_TONE: Record<RunStatus, "neutral" | "positive" | "negative" | "warning"> = {
  pending: "neutral",
  running: "warning",
  completed: "positive",
  failed: "negative",
};

const AGGREGATION_LABEL: Record<MeasureAggregation, string> = {
  sum: "Added together",
  mean: "Averaged",
  median: "Median value",
  last: "Latest value",
  min: "Lowest value",
  max: "Highest value",
};

function RunCard({
  run,
  clearing,
  clearDisabled,
  onOpen,
  onClear,
}: {
  run: ForecastRun;
  clearing: boolean;
  clearDisabled: boolean;
  onOpen: (run: ForecastRun) => void;
  onClear: (run: ForecastRun) => void;
}) {
  const ready = run.status === "completed";
  const working = run.status === "pending" || run.status === "running";
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate text-subhead font-semibold text-text-primary">{run.name}</h2>
          <p className="mt-0.5 text-caption text-text-muted">
            {formatRelativeTime(run.created_at)} · {run.frequency} · {run.horizon} periods
          </p>
        </div>
        <Badge tone={STATUS_TONE[run.status]}>{run.status}</Badge>
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <div>
          <dt className="text-caption text-text-muted">Method used</dt>
          <dd className="mt-0.5 truncate text-meta font-medium text-text-primary">
            {run.selected_model ? humanizeModel(run.selected_model) : "Not selected"}
          </dd>
        </div>
        <div>
          <dt className="text-caption text-text-muted">Confidence band</dt>
          <dd className="mt-0.5 text-meta font-medium text-text-primary num">
            {Math.round(run.confidence_level * 100)}%
          </dd>
        </div>
        <div>
          <dt className="text-caption text-text-muted">Covers</dt>
          <dd className="mt-0.5 text-meta font-medium text-text-primary">
            {run.forecast_start && run.forecast_end ? `${run.forecast_start} – ${run.forecast_end}` : "Pending"}
          </dd>
        </div>
        <div>
          <dt className="text-caption text-text-muted">Duplicate periods</dt>
          <dd className="mt-0.5 text-meta font-medium text-text-primary">
            {AGGREGATION_LABEL[run.aggregation]}
          </dd>
        </div>
        <div className="col-span-2">
          {/* Without this a run that forecast 500 series reads exactly like one
              that forecast a single total. */}
          <dt className="text-caption text-text-muted">Broken down by</dt>
          <dd className="mt-0.5 truncate text-meta font-medium text-text-primary">
            {run.group_by.length > 0
              ? `${run.group_by.join(" and ")} — ${run.series_count.toLocaleString()} lines`
              : "Nothing — one overall total"}
          </dd>
        </div>
      </dl>

      {run.error_message ? (
        <p className="mt-3 rounded-chip bg-negative-soft px-2 py-1.5 text-caption text-negative">
          {run.error_message}
        </p>
      ) : null}

      <Scorecard run={run} />

      <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="primary"
            icon={working ? Activity : Eye}
            disabled={!ready && !working}
            onClick={() => onOpen(run)}
          >
            {working ? "Track progress" : "View forecast"}
          </Button>
          <Button
            size="sm"
            icon={Download}
            disabled={!ready}
            onClick={() => downloadExport(run.id, "csv")}
          >
            CSV
          </Button>
          <Button
            size="sm"
            icon={FileText}
            disabled={!ready}
            onClick={() => downloadExport(run.id, "pdf")}
          >
            PDF report
          </Button>
        </div>
        <Button
          size="sm"
          variant="danger"
          icon={Trash2}
          loading={clearing}
          disabled={clearDisabled || run.status === "pending" || run.status === "running"}
          onClick={() => onClear(run)}
        >
          Clear run
        </Button>
      </div>
    </Card>
  );
}

export function ReportsWorkspace() {
  const router = useRouter();
  const { data, isLoading, isError, error, refetch, isFetching, dataUpdatedAt } =
    useForecastRuns();
  const openModal = useUiStore((state) => state.openModal);
  const selectedRunId = useUiStore((state) => state.runId);
  const activeRunId = useUiStore((state) => state.activeRunId);
  const setRunId = useUiStore((state) => state.setRunId);
  const setActiveRun = useUiStore((state) => state.setActiveRun);
  const clearRun = useDeleteForecastRun();
  const runs = data ?? [];
  const completed = runs.filter((run) => run.status === "completed").length;
  const active = runs.filter((run) => run.status === "pending" || run.status === "running").length;
  const failed = runs.filter((run) => run.status === "failed").length;

  function handleClear(run: ForecastRun) {
    const confirmed = window.confirm(
      `Clear "${run.name}"? This permanently removes its forecast results and generated exports.`,
    );
    if (!confirmed) return;

    clearRun.mutate(run.id, {
      onSuccess: () => {
        if (selectedRunId === run.id) setRunId(null);
        if (activeRunId === run.id) setActiveRun(null);
      },
    });
  }

  function handleOpen(run: ForecastRun) {
    if (run.status === "pending" || run.status === "running") {
      setActiveRun(run.id);
      openModal("configure-forecast");
      return;
    }
    setRunId(run.id);
    router.push("/");
  }

  return (
    <main id="main-content" className="scroll-thin min-w-0 flex-1 overflow-y-auto bg-canvas px-4 py-4 sm:px-6 sm:py-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-heading font-semibold tracking-[-0.015em] text-text-primary">Reports</h1>
          <p className="mt-0.5 text-meta text-text-secondary">
            Review every run and export planning-ready data.
          </p>
        </div>
        <div className="flex gap-2">
          <RefreshButton
            updatedAt={dataUpdatedAt}
            isFetching={isFetching}
            onRefresh={() => void refetch()}
          />
          <Button variant="primary" icon={Plus} onClick={() => openModal("configure-forecast")}>New forecast</Button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[["All runs", runs.length], ["Completed", completed], ["In progress", active], ["Failed", failed]].map(([label, value]) => (
          <Card key={String(label)} className="p-3.5">
            <p className="text-caption text-text-muted">{label}</p>
            <p className="mt-1 text-kpi font-semibold text-text-primary num">{value}</p>
          </Card>
        ))}
      </div>

      {isLoading ? (
        <div className="mt-4 space-y-3" aria-hidden>
          {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-48 w-full" />)}
        </div>
      ) : isError ? (
        <Card className="mt-4"><ErrorState error={error} onRetry={() => void refetch()} /></Card>
      ) : runs.length === 0 ? (
        <Card className="mt-4">
          <EmptyState
            icon={FileBarChart2}
            title="No reports yet"
            message="Run a forecast to create a CSV extract and a PDF report."
            action={<Button variant="primary" onClick={() => openModal("configure-forecast")}>Create a forecast</Button>}
          />
        </Card>
      ) : (
        <section className="mt-4 space-y-3" aria-label="Forecast reports">
          {runs.map((run) => (
            <RunCard
              key={run.id}
              run={run}
              clearing={clearRun.isPending && clearRun.variables === run.id}
              clearDisabled={clearRun.isPending}
              onOpen={handleOpen}
              onClear={handleClear}
            />
          ))}
        </section>
      )}
    </main>
  );
}
