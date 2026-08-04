"use client";


import { AddConnectorModal } from "@/components/connectors/add-connector-modal";
import { ConnectorImportModal } from "@/components/connectors/connector-import-modal";
import { ConnectorRail } from "@/components/connectors/connector-rail";
import { ForecastModal } from "@/components/dashboard/forecast-modal";
import { ModelDetailModal } from "@/components/dashboard/model-detail-modal";
import { RailDrawer } from "@/components/dashboard/rail-drawer";
import { SettingsModal } from "@/components/dashboard/settings-modal";
import { TopHeader } from "@/components/dashboard/top-header";
import { UploadDatasetModal } from "@/components/dashboard/upload-dataset-modal";
import { Workspace } from "@/components/dashboard/workspace";
import { AllInsightsModal } from "@/components/insights/all-insights-modal";
import { InsightDrawer } from "@/components/insights/insight-drawer";
import { InsightsRail } from "@/components/insights/insights-rail";

export function DashboardShell() {
  return (
    // 100dvh rather than 100vh: mobile browsers shrink the visual viewport as
    // their chrome slides away, and vh does not follow.
    <div className="flex h-[100dvh] flex-col overflow-hidden bg-canvas">
      <TopHeader />

      <div className="flex min-h-0 flex-1">
        <ConnectorRail />
        <Workspace />
        <InsightsRail />
      </div>

      <RailDrawer />

      <AddConnectorModal />
      <ConnectorImportModal />
      <UploadDatasetModal />
      <ForecastModal />
      <ModelDetailModal />
      <AllInsightsModal />
      <SettingsModal />
      <InsightDrawer />
    </div>
  );
}
