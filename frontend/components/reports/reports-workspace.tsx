"use client";

import { Activity, Download, Eye, FileBarChart2, FileText, Plus, Search, Trash2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Scorecard } from "@/components/reports/scorecard";
import { RefreshButton } from "@/components/ui/refresh-button";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  Skeleton,
} from "@/components/ui/primitives";
import { Select } from "@/components/ui/select";
import { downloadExport, useDeleteForecastRun, useForecastRuns } from "@/hooks/use-dashboard";
import { useDebounced } from "@/hooks/use-debounced";
import { formatDateRange, formatRelativeTime, humanizeKey, humanizeModel } from "@/lib/format";
import { labelGranularity, periodWord } from "@/lib/periods";
import { cn } from "@/lib/utils";
import { confirm } from "@/stores/confirm-store";
import { useUiStore } from "@/stores/ui-store";
import type { ForecastRun, MeasureAggregation, RunSort, RunState, RunStatus } from "@/types/api";

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

type StateFilter = RunState | "all";

const PAGE_SIZE = 20;

const SORT_OPTIONS: { value: RunSort; label: string }[] = [
  { value: "newest", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "name", label: "Name A–Z" },
  { value: "series", label: "Most lines" },
];

function describeBreakdown(run: ForecastRun): string {
  if (run.group_by.length > 0) {
    const lines = run.series_count.toLocaleString();
    return `${run.group_by.join(" and ")} — ${lines} forecast separately`;
  }

  const splits = [run.region_column, run.category_column].filter(Boolean) as string[];
  if (splits.length > 0) {
    return `${splits.join(" and ")} — charted as a split of one total`;
  }

  return "Nothing — one overall total";
}

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
            {formatRelativeTime(run.created_at)} · {humanizeKey(run.frequency)} ·{" "}
            {run.horizon} {periodWord(run.frequency, run.horizon)} ahead
          </p>
        </div>
        <Badge tone={STATUS_TONE[run.status]}>{humanizeKey(run.status)}</Badge>
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
            {run.forecast_start && run.forecast_end
              ? formatDateRange(
                  run.forecast_start,
                  run.forecast_end,
                  labelGranularity(run.frequency),
                )
              : "Pending"}
          </dd>
        </div>
        <div>
          <dt className="text-caption text-text-muted">Duplicate periods</dt>
          <dd className="mt-0.5 text-meta font-medium text-text-primary">
            {AGGREGATION_LABEL[run.aggregation]}
          </dd>
        </div>
        <div className="col-span-2">

          <dt className="text-caption text-text-muted">Broken down by</dt>
          <dd className="mt-0.5 truncate text-meta font-medium text-text-primary">
            {describeBreakdown(run)}
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
  const openModal = useUiStore((state) => state.openModal);
  const selectedRunId = useUiStore((state) => state.runId);
  const activeRunId = useUiStore((state) => state.activeRunId);
  const setRunId = useUiStore((state) => state.setRunId);
  const setActiveRun = useUiStore((state) => state.setActiveRun);
  const clearRun = useDeleteForecastRun();

  const [state, setState] = useState<StateFilter>("all");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<RunSort>("newest");
  const [page, setPage] = useState(0);

  const search = useDebounced(query, 250);

  const { data, isLoading, isError, error, refetch, isFetching, dataUpdatedAt, isPlaceholderData } =
    useForecastRuns({
      search: search.trim() || undefined,
      state: state === "all" ? undefined : state,
      sort,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
    });

  function change<T>(set: (value: T) => void) {
    return (value: T) => {
      set(value);
      setPage(0);
    };
  }

  const shown = data?.rows ?? [];
  const counts: { key: StateFilter; label: string; value: number }[] = [
    { key: "all", label: "All runs", value: data?.counts.all ?? 0 },
    { key: "completed", label: "Completed", value: data?.counts.completed ?? 0 },
    { key: "active", label: "In progress", value: data?.counts.active ?? 0 },
    { key: "failed", label: "Failed", value: data?.counts.failed ?? 0 },
  ];

  const total = data?.total ?? 0;
  const showing = data ? `${data.offset + 1}–${data.offset + shown.length} of ${total}` : "";

  async function handleClear(run: ForecastRun) {
    const confirmed = await confirm({
      title: "Clear this run?",
      message: `"${run.name}" loses its forecast results and generated exports permanently.`,
      confirmLabel: "Clear run",
    });
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
    router.push("/dashboard");
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
        {counts.map((count) => {
          const selected = state === count.key;
          return (
            <button
              key={count.key}
              type="button"
              aria-pressed={selected}
              onClick={() => change(setState)(count.key)}
              className={cn(
                "rounded-card border bg-surface p-3.5 text-left transition-colors duration-fast",
                selected
                  ? "border-accent ring-1 ring-accent"
                  : "border-border hover:border-border-strong",
              )}
            >
              <p className="text-caption text-text-muted">{count.label}</p>
              <p className="mt-1 text-kpi font-semibold text-text-primary num">{count.value}</p>
            </button>
          );
        })}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <div className="relative min-w-0 flex-1 sm:max-w-sm">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted"
            aria-hidden
          />
          <Input
            value={query}
            onChange={(event) => change(setQuery)(event.target.value)}
            placeholder="Search runs by name, column or method"
            aria-label="Search runs"
            className="pl-8"
          />
        </div>
        <Select
          value={sort}
          onChange={change(setSort)}
          options={SORT_OPTIONS}
          label="Order runs"
          className="w-[168px]"
        />
      </div>

      {isLoading ? (
        <div className="mt-4 space-y-3" aria-hidden>
          {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-48 w-full" />)}
        </div>
      ) : isError ? (
        <Card className="mt-4"><ErrorState error={error} onRetry={() => void refetch()} /></Card>
      ) : data?.counts.all === 0 ? (
        <Card className="mt-4">
          <EmptyState
            icon={FileBarChart2}
            title="No reports yet"
            message="Run a forecast to create a CSV extract and a PDF report."
            action={<Button variant="primary" onClick={() => openModal("configure-forecast")}>Create a forecast</Button>}
          />
        </Card>
      ) : shown.length === 0 ? (
        <Card className="mt-3">
          <EmptyState
            icon={Search}
            title="Nothing matches that"
            message={
              query.trim()
                ? `No run mentions "${query.trim()}"${state === "all" ? "" : " in this group"}.`
                : "No run is in this group yet."
            }
            action={
              <Button
                onClick={() => {
                  setQuery("");
                  setState("all");
                  setPage(0);
                }}
              >
                Show every run
              </Button>
            }
          />
        </Card>
      ) : (
        <>
          <section
            className={cn("mt-3 space-y-3", isPlaceholderData && "opacity-60 transition-opacity")}
            aria-label="Forecast reports"
          >
            {shown.map((run) => (
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

          {total > PAGE_SIZE ? (
            <div className="mt-3 flex items-center justify-between gap-3">
              <p className="text-caption text-text-muted num">{showing}</p>
              <div className="flex items-center gap-1.5">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={page === 0}
                  onClick={() => setPage((current) => Math.max(0, current - 1))}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={(page + 1) * PAGE_SIZE >= total}
                  onClick={() => setPage((current) => current + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          ) : null}
        </>
      )}
    </main>
  );
}
