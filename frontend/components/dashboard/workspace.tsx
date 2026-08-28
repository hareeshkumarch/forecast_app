"use client";

import { ChevronRight, Plus, Upload } from "lucide-react";

import { ForecastVsActual } from "@/components/charts/forecast-vs-actual";
import { AccuracyPanel } from "@/components/dashboard/accuracy-panel";
import { BreakdownPanel } from "@/components/dashboard/breakdown-panel";
import { DecisionPanel } from "@/components/dashboard/decision-panel";
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

  const firstRun = isSuccess && !summary.has_data;
  const breakdowns = summary?.breakdowns ?? [];

  return (
    <main id="main-content" className="workspace scroll-thin min-w-0 flex-1 overflow-y-auto bg-canvas py-4 sm:py-5">
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
                "inline-flex h-11 items-center gap-1 rounded-chip border border-border bg-surface-muted px-2 fine:h-8",
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

      {isPending ? (
        <div className="mt-4 space-y-3" aria-busy data-workspace="loading">
          <Skeleton className="h-[92px] w-full rounded-card" />
          <Skeleton className="h-[220px] w-full rounded-card" />
        </div>
      ) : isError ? (
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

          <DecisionPanel className="mt-3" />

          <div className="grid-charts stagger mt-3">
            <ForecastVsActual />
            {breakdowns[0] ? (
              <BreakdownPanel key={breakdowns[0].column} breakdown={breakdowns[0]} />
            ) : (
              <DriverTable />
            )}
          </div>

          {breakdowns.length > 0 ? (
            <div className="grid-panels stagger mt-3">
              {breakdowns.slice(1).map((breakdown) => (
                <BreakdownPanel key={breakdown.column} breakdown={breakdown} />
              ))}

              <DriverTable className={breakdowns.length % 2 === 1 ? "panel-span" : undefined} />
            </div>
          ) : null}

          <AccuracyPanel className="mt-3" />
        </div>
      )}
    </main>
  );
}
