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
import {
  useForecastRuns,
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
import type { SeriesRow, SeriesSort } from "@/types/api";

const PAGE_SIZE = 25;

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
    hint: "Total, groups and the grain itself",
  },
  {
    value: "leaf",
    label: "The grain only",
    hint: "Just the series you forecast at",
  },
];

/**
 * The planner's screen: which series need a human this week.
 *
 * The dashboard answers "how is the business doing". This answers "where is
 * the forecast wrong, and does it matter" — which is a different question and
 * a different ordering, so it is a different screen.
 */
export function SeriesWorkspace() {
  const filters = useDashboardFilters();
  const { data: runs, isPending, isError, error, refetch } = useForecastRuns();

  const run = useMemo(() => {
    if (!runs?.length) return null;
    if (filters.runId) return runs.find((r) => r.id === filters.runId) ?? null;
    return runs.find((r) => r.status === "completed") ?? null;
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
              : "Forecasts broken down by the grain a run was given"}
          </p>
        </header>

        {/* "No completed run yet" is a claim, not a placeholder: shown while
            the runs are still loading it tells someone with fifty of them that
            they have none. */}
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
              message="Pick a forecast grain when you start a run — SKU by store, account by product — and every combination is forecast in its own right."
              action={<NewForecastButton label="Run one at a grain" />}
            />
          </Card>
        ) : (
          <SeriesTable runId={run.id} leafLevel={run.group_by.length} />
        )}
      </div>
    </main>
  );
}

/** An empty screen that only names what is missing is a dead end. */
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
  const [scope, setScope] = useState("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<SeriesRow | null>(null);

  const query: SeriesQuery = {
    sort,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    // The grain is the deepest level, which is however many columns it has.
    ...(scope === "leaf" ? { level: leafLevel } : {}),
    ...(search.trim() ? { search: search.trim() } : {}),
  };

  const { data, isLoading, isError, error, refetch, isPlaceholderData } =
    useForecastSeries(runId, query);

  // Changing what is asked for has to start from the first page, or the offset
  // outruns a shorter result and the list comes back empty.
  function change<T>(set: (value: T) => void) {
    return (value: T) => {
      set(value);
      setPage(0);
    };
  }

  const rows = data?.rows ?? [];
  // Whether the numbers are money is the server's call, not a second guess at
  // the column name that could disagree with what the export decided.
  const currency = data?.currency ?? true;
  // The realized column exists only once this run has been graded against
  // actuals; before that there is nothing behind it but empty cells.
  const scored = rows.some((row) => row.scored_periods > 0);
  const showing = data
    ? `${data.offset + 1}–${data.offset + rows.length} of ${data.total}`
    : "";

  return (
    <div className="space-y-3">
      {/* Finding the worst series and not being able to look at it is where
          this screen used to stop. Level 0 is the run's own total, so it
          scopes to nothing and the chart falls back to the top line. */}
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

      <Card className="overflow-hidden">
        <PanelHeader
          title="Where to look first"
          subtitle={
            sort === "value_at_risk"
              ? "The lines where the most money could be wrong, at the top"
              : SORTS.find((s) => s.value === sort)?.hint
          }
        />

        {/* Below the header rather than beside it: three controls and a title do
          not share a phone's width, and the title loses. */}
        <div className="flex flex-wrap items-center gap-1.5 px-4 pb-3">
          {/* Its own row on a phone: given flex-1 it would shrink to the icon
            rather than push the fixed-width selects onto the next line. */}
          <div className="relative basis-full sm:basis-auto">
            <Search
              className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-text-muted"
              aria-hidden
            />
            <Input
              value={search}
              onChange={(event) => change(setSearch)(event.target.value)}
              placeholder="Find a series"
              aria-label="Find a series"
              className="w-full pl-7 sm:w-[160px]"
            />
          </div>
          <Select
            value={scope}
            onChange={change(setScope)}
            options={LEVELS}
            label="Which levels to show"
            className="w-[140px]"
            menuClassName="w-[240px]"
          />
          <Select
            value={sort}
            onChange={change((value: string) => setSort(value as SeriesSort))}
            options={SORTS}
            label="Order the list by"
            className="w-[150px]"
            menuClassName="w-[280px]"
          />
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
              search
                ? `No series with “${search}” in its name.`
                : "This run stored no series."
            }
          />
        ) : (
          <>
            <div className="overflow-x-auto">
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
                    {/* Trend is the one a phone can lose: accuracy is what says
                      whether the number beside it can be trusted. */}
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
                    {/* Only once something has been graded. A column of
                      dashes on an unscored run is noise, not information. */}
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
      {/* max-w on the cell, not the span: a table cell grows to its content
          and would push the columns that matter off a phone's screen. */}
      <td className="max-w-[46vw] px-4 py-2 sm:max-w-none">
        {/* A real button, so the chart is reachable by keyboard and the row
            announces what selecting it does. */}
        <button
          type="button"
          // Without this the click also reaches the row's handler and the
          // second toggle undoes the first.
          onClick={(event) => {
            event.stopPropagation();
            onSelect();
          }}
          aria-pressed={selected}
          className="flex min-w-0 items-center gap-1.5 rounded-chip text-left"
        >
          {/* Depth is the one thing a flat list of a tree has to keep. */}
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
              // Against the error its own backtest predicted: worse than
              // expected is the row worth opening, and neither number says
              // that on its own.
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
