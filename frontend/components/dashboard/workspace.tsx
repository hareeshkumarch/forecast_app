"use client";


import { Plus, Upload } from "lucide-react";

import { ForecastByCategory } from "@/components/charts/forecast-by-category";
import { ForecastVsActual } from "@/components/charts/forecast-vs-actual";
import { DriverTable } from "@/components/dashboard/driver-table";
import { KpiCards } from "@/components/dashboard/kpi-cards";
import { RegionTable } from "@/components/dashboard/region-table";
import { Badge, Button } from "@/components/ui/primitives";
import { useSummary } from "@/hooks/use-dashboard";
import { humanizeModel } from "@/lib/format";
import { useUiStore } from "@/stores/ui-store";

export function Workspace() {
  const { data: summary } = useSummary();
  const openModal = useUiStore((state) => state.openModal);

  return (
    <main className="scroll-thin min-w-0 flex-1 overflow-y-auto bg-canvas px-6 py-5">
      
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-heading font-semibold tracking-[-0.015em] text-text-primary">
            Overview
          </h2>
          <p className="mt-0.5 text-meta text-text-secondary">
            Comprehensive view of your forecast performance
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {summary?.selected_model ? (
            <Badge tone="neutral" className="h-7 px-2">
              Model: {humanizeModel(summary.selected_model)}
            </Badge>
          ) : null}
          <Button variant="secondary" icon={Upload} onClick={() => openModal("upload-dataset")}>
            Upload Data
          </Button>
          <Button variant="primary" icon={Plus} onClick={() => openModal("configure-forecast")}>
            New Forecast
          </Button>
        </div>
      </div>

      
      <div className="mt-4">
        <KpiCards />
      </div>

      
      <div className="mt-3 grid grid-cols-[52fr_48fr] gap-3">
        <ForecastVsActual />
        <ForecastByCategory />
      </div>

      
      <div className="mt-3 grid grid-cols-2 gap-3">
        <RegionTable />
        <DriverTable />
      </div>
    </main>
  );
}
