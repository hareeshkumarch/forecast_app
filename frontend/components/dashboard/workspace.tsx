"use client";


import { ChevronRight, Plus, Upload } from "lucide-react";

import { ForecastByCategory } from "@/components/charts/forecast-by-category";
import { ForecastVsActual } from "@/components/charts/forecast-vs-actual";
import { DriverTable } from "@/components/dashboard/driver-table";
import { KpiCards } from "@/components/dashboard/kpi-cards";
import { RegionTable } from "@/components/dashboard/region-table";
import { Button } from "@/components/ui/primitives";
import { useSummary } from "@/hooks/use-dashboard";
import { humanizeModel } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui-store";

export function Workspace() {
  const { data: summary } = useSummary();
  const openModal = useUiStore((state) => state.openModal);

  return (
    <main className="workspace scroll-thin min-w-0 flex-1 overflow-y-auto bg-canvas px-4 py-4 sm:px-6 sm:py-5">
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
          {summary?.selected_model ? (
            <button
              type="button"
              onClick={() => openModal("model-detail")}
              title="How this model was chosen"
              className={cn(
                "inline-flex h-8 items-center gap-1 rounded-chip border border-border bg-surface-muted px-2",
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

      <div className="mt-4">
        <KpiCards />
      </div>

      <div className="grid-charts mt-3">
        <ForecastVsActual />
        <ForecastByCategory />
      </div>

      <div className="grid-panels mt-3">
        <RegionTable />
        <DriverTable />
      </div>
    </main>
  );
}
