"use client";

import dynamic from "next/dynamic";

import { SignInPrompt } from "@/components/auth/sign-in-gate";
import { useAuth } from "@/stores/auth-store";
import type { ComponentType } from "react";

import { AppSidebar, type AppSection } from "@/components/dashboard/app-sidebar";
import { CommandPalette } from "@/components/dashboard/command-palette";
import {
  ForecastRunPill,
  ForecastRunProvider,
} from "@/components/dashboard/forecast-run-watcher";
import { TopHeader } from "@/components/dashboard/top-header";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Skeleton } from "@/components/ui/primitives";
import { Toaster } from "@/components/ui/toaster";
import { useUiStore } from "@/stores/ui-store";

function WorkspaceFallback() {
  return (
    <main className="min-w-0 flex-1 bg-canvas px-4 py-4 sm:px-6 sm:py-5" aria-busy="true">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2"><Skeleton className="h-6 w-36" /><Skeleton className="h-3 w-64 max-w-[60vw]" /></div>
        <Skeleton className="h-8 w-24" />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-24" />)}
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-2"><Skeleton className="h-72" /><Skeleton className="h-72" /></div>
    </main>
  );
}

const Workspace = dynamic(
  () => import("@/components/dashboard/workspace").then((module) => module.Workspace),
  { loading: WorkspaceFallback },
);
const SeriesWorkspace = dynamic(
  () => import("@/components/series/series-workspace").then((module) => module.SeriesWorkspace),
  { loading: WorkspaceFallback },
);
const DatasetsWorkspace = dynamic(
  () => import("@/components/datasets/datasets-workspace").then((module) => module.DatasetsWorkspace),
  { loading: WorkspaceFallback },
);
const ReportsWorkspace = dynamic(
  () => import("@/components/reports/reports-workspace").then((module) => module.ReportsWorkspace),
  { loading: WorkspaceFallback },
);
const ScenariosWorkspace = dynamic(
  () => import("@/components/scenarios/scenarios-workspace").then((module) => module.ScenariosWorkspace),
  { loading: WorkspaceFallback },
);
const ConnectorsWorkspace = dynamic(
  () => import("@/components/connectors/connectors-workspace").then((module) => module.ConnectorsWorkspace),
  { loading: WorkspaceFallback },
);
const UsageWorkspace = dynamic(
  () => import("@/components/usage/usage-workspace").then((module) => module.UsageWorkspace),
  { loading: WorkspaceFallback },
);
const SettingsWorkspace = dynamic(
  () => import("@/components/settings/settings-workspace").then((module) => module.SettingsWorkspace),
  { loading: WorkspaceFallback },
);

const InsightsRail = dynamic(
  () => import("@/components/insights/insights-rail").then((module) => module.InsightsRail),
);
const RailDrawer = dynamic(
  () => import("@/components/dashboard/rail-drawer").then((module) => module.RailDrawer),
);
const AddConnectorModal = dynamic(
  () => import("@/components/connectors/add-connector-modal").then((module) => module.AddConnectorModal),
);
const ConnectorImportModal = dynamic(
  () => import("@/components/connectors/connector-import-modal").then((module) => module.ConnectorImportModal),
);
const UploadDatasetModal = dynamic(
  () => import("@/components/dashboard/upload-dataset-modal").then((module) => module.UploadDatasetModal),
);
const ForecastModal = dynamic(
  () => import("@/components/dashboard/forecast-modal").then((module) => module.ForecastModal),
);
const ModelDetailModal = dynamic(
  () => import("@/components/dashboard/model-detail-modal").then((module) => module.ModelDetailModal),
);
const AllInsightsModal = dynamic(
  () => import("@/components/insights/all-insights-modal").then((module) => module.AllInsightsModal),
);
const SettingsModal = dynamic(
  () => import("@/components/dashboard/settings-modal").then((module) => module.SettingsModal),
);
const InsightDrawer = dynamic(
  () => import("@/components/insights/insight-drawer").then((module) => module.InsightDrawer),
);

const WORKSPACES: Record<AppSection, ComponentType> = {
  dashboard: Workspace,
  series: SeriesWorkspace,
  datasets: DatasetsWorkspace,
  reports: ReportsWorkspace,
  scenarios: ScenariosWorkspace,
  connectors: ConnectorsWorkspace,
  usage: UsageWorkspace,
  settings: SettingsWorkspace,
};

function LazyOverlayHost() {
  const modal = useUiStore((state) => state.modal);
  const mobileRail = useUiStore((state) => state.mobileRail);
  const insight = useUiStore((state) => state.insightDrawer);

  return (
    <>
      {mobileRail ? <RailDrawer /> : null}
      {modal === "add-connector" || modal === "edit-connector" ? <AddConnectorModal /> : null}
      {modal === "connector-import" ? <ConnectorImportModal /> : null}
      {modal === "upload-dataset" ? <UploadDatasetModal /> : null}
      {modal === "configure-forecast" ? <ForecastModal /> : null}
      {modal === "model-detail" ? <ModelDetailModal /> : null}
      {modal === "all-insights" ? <AllInsightsModal /> : null}
      {modal === "settings" ? <SettingsModal /> : null}
      {insight ? <InsightDrawer /> : null}
    </>
  );
}

export function DashboardShell({ section = "dashboard" }: { section?: AppSection }) {
  const SectionWorkspace = WORKSPACES[section];
  const { user, ready, configured } = useAuth();

  // One gate for all eight sections, because every page in the app is this
  // shell with a different workspace in it. Put it on the pages instead and
  // the ninth page is the one that ships unguarded.
  if (configured && ready && !user) {
    return (
      <div className="min-h-[100dvh] bg-canvas">
        <SignInPrompt />
      </div>
    );
  }

  return (
    // The run watcher wraps the shell rather than sitting inside the overlay
    // host: it has to outlive the forecast dialog, which is unmounted the
    // moment that dialog closes.
    <ForecastRunProvider>
      <div className="app-shell-grid flex h-[100dvh] flex-col overflow-hidden bg-canvas">
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
        <CommandPalette />
        <Toaster />
        <LazyOverlayHost />
        <ForecastRunPill />
        <ConfirmDialog />
      </div>
    </ForecastRunProvider>
  );
}
