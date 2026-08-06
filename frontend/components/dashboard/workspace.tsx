"use client";


import { ChevronRight, Plus, Upload } from "lucide-react";

import { ForecastVsActual } from "@/components/charts/forecast-vs-actual";
import { BreakdownPanel } from "@/components/dashboard/breakdown-panel";
import { DriverTable } from "@/components/dashboard/driver-table";
import { GettingStarted } from "@/components/dashboard/getting-started";
import { KpiCards } from "@/components/dashboard/kpi-cards";
import { ModelHealthStrip } from "@/components/dashboard/model-health-strip";
import { Button, Card, ErrorState, Skeleton } from "@/components/ui/primitives";
import { RefreshButton } from "@/components/ui/refresh-button";
import { useDashboardRefresh, useSummary } from "@/hooks/use-dashboard";
import { humanizeModel } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";

export function Workspace() {
  const { data: summary, isSuccess, isPending, isError, error, refetch } = useSummary();
  const live = useDashboardRefresh();
  const openModal = useUiStore((state) => state.openModal);

  // Only once the summary has actually answered — a slow first load must not
  // flash the guide at someone who has fifty runs, and must not shimmer a
  // whole dashboard at someone who is about to be shown the guide instead.
  const firstRun = isSuccess && !summary.has_data;
  const breakdowns = summary?.breakdowns ?? [];

  return (
    <main id="main-content" className="workspace scroll-thin min-w-0 flex-1 overflow-y-auto bg-canvas px-4 py-4 sm:px-6 sm:py-5">
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
        <div className="min-w-0">
          <h2 className="text-heading font-semibold tracking-[-0.015em] text-text-primary">
            Overview
          </h2>
          <p className="mt-0.5 text-meta text-text-secondary">
            Comprehensive view of your forecast performance
          </p>
        </div>

        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
          {/* Only once there is something on screen worth being stale. */}
          {isSuccess && summary.has_data ? (
            <RefreshButton
              updatedAt={live.updatedAt}
              isFetching={live.isFetching}
              onRefresh={live.refresh}
            />
          ) : null}

          {summary?.selected_model ? (
            <button
              type="button"
              onClick={() => openModal("model-detail")}
              title="How this model was chosen"
              className={cn(
                "inline-flex h-11 items-center gap-1 rounded-chip border border-border bg-surface-muted px-2 sm:h-8",
                "text-caption font-medium text-text-secondary",
                "transition-colors duration-fast hover:border-border-strong hover:text-text-primary",
              )}
            >
              <span className="truncate">Model: {humanizeModel(summary.selected_model)}</span>
              <ChevronRight className="h-3 w-3 shrink-0 text-text-muted" aria-hidden />
            </button>
          ) : null}

          <Button
            variant="secondary"
            icon={Upload}
            onClick={() => openModal("upload-dataset")}
            className="flex-1 sm:flex-none"
          >
            Upload Data
          </Button>
          <Button
            variant="primary"
            icon={Plus}
            onClick={() => openModal("configure-forecast")}
            className="flex-1 sm:flex-none"
          >
            New Forecast
          </Button>
        </div>
      </div>

      {/*
       * Before the first run the five analytical panels have nothing to say,
       * and stacking five "no data yet" cards under the guide buries the one
       * thing the screen is for. The guide gets the screen until there is a
       * forecast to show.
       */}
      {isPending ? (
        <div className="mt-4 space-y-3" aria-busy data-workspace="loading">
          <Skeleton className="h-[92px] w-full rounded-card" />
          <Skeleton className="h-[220px] w-full rounded-card" />
        </div>
      ) : isError ? (
        /*
         * A question the summary could not answer is not the same as one it
         * has not answered yet, and treating them alike left this screen
         * shimmering for ever with the API down.
         *
         * It also looped: every panel below asks for the same summary, so the
         * moment the query gave up and the panels mounted, one of them
         * refetched on mount, the query went back to pending, the panels
         * unmounted, and the whole dashboard oscillated a few times a second
         * against a backend that was not there.
         */
        <div className="mt-4" data-workspace="error">
          <Card>
            <ErrorState
              error={error}
              title="We can't reach your data right now"
              message="Nothing has been lost — your forecasts are safe. This usually clears on its own in a moment."
              onRetry={() => void refetch()}
            />
          </Card>
        </div>
      ) : firstRun ? (
        <div className="mt-4" data-first-run data-workspace="first-run">
          <GettingStarted />
        </div>
      ) : (
        <div data-workspace="data">
          <div className="mt-4">
            <KpiCards />
          </div>

          <ModelHealthStrip />

          {/*
            * The panels come from the data, not from a fixture. A dataset with
            * no dimensions gets the forecast and its drivers and no empty
            * cards asking about regions it has never had; one with three gets
            * three splits, each titled with the customer's own column name.
            */}
          <div className="grid-charts mt-3">
            <ForecastVsActual />
            {breakdowns[0] ? (
              <BreakdownPanel key={breakdowns[0].column} breakdown={breakdowns[0]} />
            ) : (
              <DriverTable />
            )}
          </div>

          {/*
            * Everything below the first row shares one two-column flow rather
            * than each getting a row of its own. Two breakdowns used to leave
            * two half-empty rows — the second split alone on the left, the
            * driver table alone on the left below it — with a column of white
            * space running down the right of both. An odd one out spans the
            * full width instead of leaving a hole, which the driver table is
            * glad of anyway.
            */}
          {breakdowns.length > 0 ? (
            <div className="grid-panels mt-3">
              {breakdowns.slice(1).map((breakdown) => (
                <BreakdownPanel key={breakdown.column} breakdown={breakdown} />
              ))}
              {/*
                * This row holds `breakdowns.length` panels in total: every
                * split after the first, plus the driver table. The table is
                * the odd one out when that total is odd.
                */}
              <DriverTable className={breakdowns.length % 2 === 1 ? "panel-span" : undefined} />
            </div>
          ) : null}
        </div>
      )}
    </main>
  );
}
