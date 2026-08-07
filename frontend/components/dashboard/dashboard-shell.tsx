"use client";

import type { ComponentType } from "react";

import { AddConnectorModal } from "@/components/connectors/add-connector-modal";
import { ConnectorImportModal } from "@/components/connectors/connector-import-modal";
import { ConnectorsWorkspace } from "@/components/connectors/connectors-workspace";
import { DatasetsWorkspace } from "@/components/datasets/datasets-workspace";
import { AppSidebar, type AppSection } from "@/components/dashboard/app-sidebar";
import { CommandPalette } from "@/components/dashboard/command-palette";
import { ForecastModal } from "@/components/dashboard/forecast-modal";
import { ModelDetailModal } from "@/components/dashboard/model-detail-modal";
import { RailDrawer } from "@/components/dashboard/rail-drawer";
import { SettingsModal } from "@/components/dashboard/settings-modal";
import { TopHeader } from "@/components/dashboard/top-header";
import { UploadDatasetModal } from "@/components/dashboard/upload-dataset-modal";
import { Workspace } from "@/components/dashboard/workspace";
import { ReportsWorkspace } from "@/components/reports/reports-workspace";
import { SeriesWorkspace } from "@/components/series/series-workspace";
import { SettingsWorkspace } from "@/components/settings/settings-workspace";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Toaster } from "@/components/ui/toaster";
import { AllInsightsModal } from "@/components/insights/all-insights-modal";
import { InsightDrawer } from "@/components/insights/insight-drawer";
import { InsightsRail } from "@/components/insights/insights-rail";
import { UsageWorkspace } from "@/components/usage/usage-workspace";

const WORKSPACES: Record<AppSection, ComponentType> = {
  dashboard: Workspace,
  series: SeriesWorkspace,
  datasets: DatasetsWorkspace,
  reports: ReportsWorkspace,
  connectors: ConnectorsWorkspace,
  usage: UsageWorkspace,
  settings: SettingsWorkspace,
};

export function DashboardShell({ section = "dashboard" }: { section?: AppSection }) {
  const SectionWorkspace = WORKSPACES[section];
  return (
    <div className="flex h-[100dvh] flex-col overflow-hidden bg-canvas">
      <a
        href="#main-content"
        className="fixed left-3 top-3 z-[100] -translate-y-20 rounded-input bg-accent px-3 py-2 text-on-accent focus:translate-y-0"
      >
        Skip to main content
      </a>
      <TopHeader section={section} />

      <div className="flex min-h-0 flex-1">
        <AppSidebar />
        <SectionWorkspace />
        {section === "dashboard" ? <InsightsRail /> : null}
      </div>

      <RailDrawer />
      <CommandPalette />
      <Toaster />

      <AddConnectorModal />
      <ConnectorImportModal />
      <UploadDatasetModal />
      <ForecastModal />
      <ModelDetailModal />
      <AllInsightsModal />
      <SettingsModal />
      <InsightDrawer />
      <ConfirmDialog />
    </div>
  );
}
