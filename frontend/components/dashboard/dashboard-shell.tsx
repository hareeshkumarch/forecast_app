"use client";


import { AddConnectorModal } from "@/components/connectors/add-connector-modal";
import { ConnectorRail } from "@/components/connectors/connector-rail";
import { ForecastModal } from "@/components/dashboard/forecast-modal";
import { TopHeader } from "@/components/dashboard/top-header";
import { UploadDatasetModal } from "@/components/dashboard/upload-dataset-modal";
import { Workspace } from "@/components/dashboard/workspace";
import { InsightDrawer } from "@/components/insights/insight-drawer";
import { InsightsRail } from "@/components/insights/insights-rail";

export function DashboardShell() {
  return (
    <div className="flex h-screen min-h-screen flex-col overflow-hidden bg-canvas">
      <TopHeader />

      <div className="flex min-h-0 flex-1">
        <ConnectorRail />
        <Workspace />
        <InsightsRail />
      </div>

      
      <AddConnectorModal />
      <UploadDatasetModal />
      <ForecastModal />
      <InsightDrawer />
    </div>
  );
}
