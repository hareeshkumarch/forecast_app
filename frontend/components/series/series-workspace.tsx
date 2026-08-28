"use client";

import {
  ChevronRight,
  Layers,
  Plus,
  Search,
  SlidersHorizontal,
  TriangleAlert,
} from "lucide-react";
import { useMemo, useState } from "react";

import { AccuracyScatter } from "@/components/charts/accuracy-scatter";
import { ForecastVsActual } from "@/components/charts/forecast-vs-actual";
import { AccuracyCell } from "@/components/dashboard/accuracy-cell";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Input,
  PanelHeader,
  Skeleton,
} from "@/components/ui/primitives";
import { Select } from "@/components/ui/select";
import { useDebounced } from "@/hooks/use-debounced";
import {
  useApiFeatures,
  useForecastRuns,
  PICKER_LIMIT,
  useForecastSeries,
  type SeriesQuery,
} from "@/hooks/use-dashboard";
import {
  formatCompact,
  formatPercent,
  formatSignedPercent,
  humanizeModel,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import { useDashboardFilters, useUiStore } from "@/stores/ui-store";
import type { SeriesRow, SeriesSort, SeriesStatus } from "@/types/api";

const PAGE_SIZE = 25;
const CHART_LIMIT = 200;

const SORTS: { value: SeriesSort; label: string; hint: string }[] = [
  {
    value: "value_at_risk",
    label: "Biggest risk",
    hint: "Where the most money could be wrong",
  },
  { value: "wmape", label: "Least accurate", hint: "The lines we trust least, first" },
  { value: "forecast_total", label: "Biggest", hint: "The largest numbers first" },
  { value: "label", label: "Name", hint: "Alphabetical" },
];

const LEVELS = [
  {
    value: "all",
    label: "Every level",
    hint: "The total, the groups, and every single line",
  },
  {
    value: "leaf",
    label: "Individual lines only",
    hint: "Skip the totals and groups above them",
  },
];

const STATES: { value: "all" | SeriesStatus; label: string; hint: string }[] = [
  { value: "all", label: "Any state", hint: "However the line was arrived at" },
  {
    value: "forecast",
    label: "Fitted",
    hint: "Forecast from this line's own history",
  },
  {
    value: "estimated",
    label: "Estimated",
    hint: "Too little history to fit, so shared out from the level above",
  },
  {
    value: "pooled",
    label: "Pooled",
    hint: "The long tail, forecast together as one line",
  },
  {
    value: "blocked",
    label: "Blocked",
    hint: "Could not be forecast at all — the reason is on the row",
  },
];

const DEFAULTS: { scope: string; state: string; search: string } = {
  scope: "all",
  state: "all",
  search: "",
};

export function SeriesWorkspace() {
  const filters = useDashboardFilters();
  const { data: runs, isPending, isError, error, refetch } = useForecastRuns({ limit: PICKER_LIMIT });

  const run = useMemo(() => {
    const rows = runs?.rows ?? [];
    if (rows.length === 0) return null;
    if (filters.runId) return rows.find((r) => r.id === filters.runId) ?? null;
    return rows.find((r) => r.status === "completed") ?? null;
  }, [runs, filters.runId]);

  return (
    <main id="main-content" className="min-w-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[1400px] px-4 py-4 sm:px-6 sm:py-5">
        <header className="mb-4">
          <h1 className="text-heading font-semibold tracking-[-0.02em] text-text-primary">
            Series
          </h1>
          <p className="mt-0.5 text-caption text-text-muted">
            {run?.group_by.length
              ? `${run.series_count.toLocaleString()} lines, broken down by ${run.group_by.join(" and ")}`
              : "Forecasts broken down by whatever a run was split on"}
          </p>
        </header>

        {isPending ? (
          <Card className="p-4">
            <Skeleton className="h-5 w-40" />
            <div className="mt-4 space-y-2">
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className="h-9 w-full" />
              ))}
            </div>
          </Card>
        ) : isError ? (
          <Card>
            <ErrorState error={error} onRetry={() => void refetch()} />
          </Card>
        ) : run === null ? (
          <Card>
            <EmptyState
              icon={Layers}
              title="No completed run yet"
              message="Run a forecast and its series will be listed here, worst first."
              action={<NewForecastButton />}
            />
          </Card>
        ) : run.group_by.length === 0 ? (
          <Card>
            <EmptyState
              icon={SlidersHorizontal}
              title="This run forecasts one total"
              message="Choose what to break the forecast down by when you start a run — product by store, account by service — and each combination gets forecast on its own."
              action={<NewForecastButton label="Run a broken-down forecast" />}
            />
          </Card>
        ) : (
          <SeriesTable runId={run.id} leafLevel={run.group_by.length} />
        )}
      </div>
    </main>
  );
}

function NewForecastButton({ label = "New Forecast" }: { label?: string }) {
  const openModal = useUiStore((state) => state.openModal);
  return (
    <Button
      variant="primary"
      icon={Plus}
      onClick={() => openModal("configure-forecast")}
    >
      {label}
    </Button>
  );
}

function SeriesTable({
  runId,
  leafLevel,
}: {
  runId: string;
  leafLevel: number;
}) {
  const [sort, setSort] = useState<SeriesSort>("value_at_risk");
  const [scope, setScope] = useState<string>(DEFAULTS.scope);
  const [requestedState, setState] = useState<string>(DEFAULTS.state);
  const [search, setSearch] = useState(DEFAULTS.search);

  const features = useApiFeatures();
  // An older backend does not declare `status` and FastAPI drops parameters it
  // does not know, so sending it would filter nothing and look like it had.
  const state = features.seriesStatusFilter ? requestedState : DEFAULTS.state;

  const settled = useDebounced(search, 250);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<SeriesRow | null>(null);

  const filtered =
    scope !== DEFAULTS.scope || state !== DEFAULTS.state || search.trim() !== DEFAULTS.search;

  const query: SeriesQuery = {
    sort,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    ...(scope === "leaf" ? { level: leafLevel } : {}),
    ...(state === "all" ? {} : { status: state as SeriesStatus }),
    ...(settled.trim() ? { search: settled.trim() } : {}),
  };

  const { data, isLoading, isError, error, refetch, isPlaceholderData } =
    useForecastSeries(runId, query);

  // The chart plots the run, not the page. It shares the filters so the two
  // never disagree, but takes the leaves in one go — a scatter of 25 rows at a
  // time would move under you every time the table paged.
  const { data: population } = useForecastSeries(runId, {
    sort: "value_at_risk",
    limit: CHART_LIMIT,
    offset: 0,
    level: leafLevel,
    ...(state === "all" ? {} : { status: state as SeriesStatus }),
    ...(settled.trim() ? { search: settled.trim() } : {}),
  });

  function change<T>(set: (value: T) => void) {
    return (value: T) => {
      set(value);
      setPage(0);
    };
  }

  function clearFilters() {
    setScope(DEFAULTS.scope);
    setState(DEFAULTS.state);
    setSearch(DEFAULTS.search);
    setPage(0);
  }

  const rows = data?.rows ?? [];

  const currency = data?.currency ?? true;

  const scored = rows.some((row) => row.scored_periods > 0);
  const showing = data
    ? `${data.offset + 1}–${data.offset + rows.length} of ${data.total}`
    : "";

  return (
    <div className="space-y-3">

      {selected ? (
        <ForecastVsActual
          seriesId={selected.level > 0 ? selected.id : null}
          title={selected.level > 0 ? selected.label : "Total"}
          subtitle={
            selected.accuracy_measured && selected.model
              ? `${humanizeModel(selected.model)} · ${formatPercent(selected.accuracy)} accurate over ${selected.folds} fold${selected.folds === 1 ? "" : "s"}`
              : (selected.blocked_reason ?? "Estimated from the group above it — not fitted on its own")
          }
          showActions={false}
        />
      ) : null}

      {population && population.rows.length > 1 ? (
        <Card>
          <PanelHeader
            title="Where the error actually is"
            subtitle={
              population.total > population.rows.length
                ? `The ${population.rows.length} biggest of ${population.total.toLocaleString()} lines, by what is at stake`
                : "Every line, by size against how wrong it tends to be"
            }
          />
          <div className="px-2 pb-2">
            <AccuracyScatter
              rows={population.rows}
              currency={population.currency}
              onSelect={setSelected}
            />
          </div>
        </Card>
      ) : null}

      <Card className="overflow-hidden">
        <PanelHeader
          title="Where to look first"
          subtitle={
            sort === "value_at_risk"
              ? "The lines where the most money could be wrong, at the top"
              : SORTS.find((s) => s.value === sort)?.hint
          }
        />

        <div className="flex flex-wrap items-center gap-2 px-4 pb-3">
          <div className="relative min-w-0 basis-full sm:basis-[180px]">
            <Search
              className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted"
              aria-hidden
            />
            <Input
              value={search}
              onChange={(event) => change(setSearch)(event.target.value)}
              placeholder="Find a series"
              aria-label="Find a series"
              className="w-full pl-7"
            />
          </div>
          <Select
            value={scope}
            onChange={change(setScope)}
            options={LEVELS}
            label="Which levels to show"
            className="w-[168px]"
            menuClassName="w-[260px]"
          />
          <Select
            value={state}
            onChange={change(setState)}
            options={STATES}
            disabled={!features.seriesStatusFilter}
            label={
              features.seriesStatusFilter
                ? "How the line was arrived at"
                : "Filtering by state needs a newer backend than this one"
            }
            className="w-[168px]"
            menuClassName="w-[300px]"
          />
          {features.seriesStatusFilter ? null : (
            <span className="text-caption text-text-muted">
              State filter needs a newer backend
            </span>
          )}
          <Select
            value={sort}
            onChange={change((value: string) => setSort(value as SeriesSort))}
            options={SORTS}
            label="Order the list by"
            className="w-[168px]"
            menuClassName="w-[280px]"
          />
          {filtered ? (
            <Button size="sm" variant="ghost" onClick={clearFilters}>
              Clear filters
            </Button>
          ) : null}
        </div>

        {isError ? (
          <ErrorState error={error} onRetry={() => void refetch()} />
        ) : isLoading ? (
          <div className="space-y-2 px-4 pb-4">
            {Array.from({ length: 6 }).map((_, index) => (
              <Skeleton key={index} className="h-9 w-full" />
            ))}
          </div>
        ) : rows.length === 0 ? (
          <EmptyState
            icon={Search}
            title="Nothing matches"
            message={
              filtered
                ? "No series matches these filters. Widen them, or clear them to see the whole run."
                : "This run stored no series."
            }
            action={
              filtered ? (
                <Button size="sm" variant="secondary" onClick={clearFilters}>
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <>
            <div className="relative overflow-x-auto">
              <table
                className={cn(
                  "w-full border-collapse text-meta sm:min-w-[720px]",
                  isPlaceholderData && "opacity-60 transition-opacity",
                )}
              >
                <thead>
                  <tr className="border-y border-border text-caption text-text-muted">
                    <th className="px-4 py-2 text-left font-medium">Series</th>
                    <th className="px-3 py-2 text-right font-medium">
                      Forecast
                    </th>

                    <th
                      className="hidden px-3 py-2 text-right font-medium sm:table-cell"
                      title="How this series has moved between the last two comparable periods"
                    >
                      Trend
                    </th>
                    <th
                      className="px-3 py-2 text-right font-medium"
                      title="How accurate we expect this line to be, from testing on its past"
                    >
                      {scored ? "Expected" : "Accuracy"}
                    </th>

                    {scored ? (
                      <th
                        className="hidden px-3 py-2 text-right font-medium sm:table-cell"
                        title="How accurate it actually turned out to be"
                      >
                        Actual
                      </th>
                    ) : null}
                    <th
                      className="px-4 py-2 text-right font-medium"
                      title="How much of this line's forecast its own error could be wrong about"
                    >
                      At risk
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <SeriesRowCells
                      key={row.id}
                      row={row}
                      currency={currency}
                      scored={scored}
                      selected={selected?.id === row.id}
                      onSelect={() =>
                        setSelected((current) =>
                          current?.id === row.id ? null : row,
                        )
                      }
                    />
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-2.5">
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
                  disabled={!data?.has_more}
                  onClick={() => setPage((current) => current + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

function SeriesRowCells({
  row,
  currency,
  scored,
  selected,
  onSelect,
}: {
  row: SeriesRow;
  currency: boolean;
  scored: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  const estimated = !row.accuracy_measured;

  return (
    <tr
      onClick={onSelect}
      aria-selected={selected}
      className={cn(
        "cursor-pointer border-b border-border last:border-0",
        selected ? "bg-accent-soft" : "hover:bg-surface-muted/60",
      )}
    >

      <td className="max-w-[46vw] px-4 py-2 sm:max-w-none">

        <button
          type="button"

          onClick={(event) => {
            event.stopPropagation();
            onSelect();
          }}
          aria-pressed={selected}
          className="flex min-w-0 items-center gap-1.5 rounded-chip text-left"
        >

          {row.level > 0 ? (
            <span
              aria-hidden
              className="shrink-0 text-text-muted"
              style={{ paddingLeft: `${(row.level - 1) * 12}px` }}
            >
              <ChevronRight className="h-3 w-3" />
            </span>
          ) : null}
          <span className="truncate font-medium text-text-primary">
            {row.level === 0 ? "Total" : row.label}
          </span>
          {row.blocked_reason ? (
            <span title={row.blocked_reason}>
              <Badge tone="warning" className="shrink-0">
                <TriangleAlert className="h-2.5 w-2.5" aria-hidden />
                Estimated
              </Badge>
            </span>
          ) : null}
        </button>
      </td>
      <td className="px-3 py-2 text-right num text-text-primary">
        {formatCompact(row.forecast_total, currency)}
      </td>
      <td
        className={cn(
          "hidden px-3 py-2 text-right num sm:table-cell",
          row.change_vs_prior === null
            ? "text-text-muted"
            : row.change_vs_prior >= 0
              ? "text-positive"
              : "text-negative",
        )}
      >
        {row.change_vs_prior === null
          ? "—"
          : formatSignedPercent(row.change_vs_prior)}
      </td>
      <td className="px-3 py-2 text-right">
        <AccuracyCell
          value={row.accuracy}
          measured={row.accuracy_measured}
          model={row.model}
          mase={row.mase}
          className="justify-end"
        />
      </td>
      {scored ? (
        <td className="hidden px-3 py-2 text-right num sm:table-cell">
          {row.realized_wmape === null ? (
            <span
              className="text-text-muted"
              title="Not graded against actuals"
            >
              —
            </span>
          ) : (
            <span

              className={
                row.wmape !== null && row.realized_wmape > row.wmape
                  ? "text-negative"
                  : "text-positive"
              }
              title={`Expected ${formatPercent(row.wmape ?? 0)} before the event`}
            >
              {formatPercent(100 - row.realized_wmape)}
            </span>
          )}
        </td>
      ) : null}
      <td className="px-4 py-2 text-right">
        {row.value_at_risk === null ? (
          <span
            className="text-text-muted"
            title="This series was estimated from its group, so there is no error to report"
          >
            —
          </span>
        ) : (
          <span
            className={cn(
              "num",
              estimated ? "text-text-muted" : "text-text-primary",
            )}
          >
            {formatCompact(row.value_at_risk, currency)}
          </span>
        )}
      </td>
    </tr>
  );
}
