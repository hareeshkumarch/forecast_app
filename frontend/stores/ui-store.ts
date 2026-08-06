import { create } from "zustand";

import type { ForecastView, Insight } from "@/types/api";

export type ModalKind =
  | "none"
  | "add-connector"
  | "edit-connector"
  | "upload-dataset"
  | "configure-forecast"
  | "connector-import"
  | "model-detail"
  | "all-insights"
  | "settings";

export type MobileRail = "navigation" | "insights" | null;

interface UiState {
  view: ForecastView;
  rangeStart: string | null;
  rangeEnd: string | null;
  runId: string | null;

  modal: ModalKind;

  modalTargetId: string | null;
  insightDrawer: Insight | null;
  mobileRail: MobileRail;

  activeRunId: string | null;

  setView: (view: ForecastView) => void;
  setRange: (start: string | null, end: string | null) => void;
  setRunId: (runId: string | null) => void;

  openModal: (modal: ModalKind, targetId?: string | null) => void;
  closeModal: () => void;

  openInsight: (insight: Insight) => void;
  closeInsight: () => void;

  openRail: (rail: Exclude<MobileRail, null>) => void;
  closeRail: () => void;

  setActiveRun: (runId: string | null) => void;
}

export const useUiStore = create<UiState>((set) => ({
  view: "base",
  rangeStart: null,
  rangeEnd: null,
  runId: null,

  modal: "none",
  modalTargetId: null,
  insightDrawer: null,
  mobileRail: null,
  activeRunId: null,

  setView: (view) => set({ view }),
  setRange: (rangeStart, rangeEnd) => set({ rangeStart, rangeEnd }),
  setRunId: (runId) => set({ runId }),

  openModal: (modal, modalTargetId = null) =>
    set({ modal, modalTargetId, mobileRail: null }),
  closeModal: () => set({ modal: "none", modalTargetId: null }),

  openInsight: (insightDrawer) => set({ insightDrawer, mobileRail: null }),
  closeInsight: () => set({ insightDrawer: null }),

  openRail: (mobileRail) => set({ mobileRail }),
  closeRail: () => set({ mobileRail: null }),

  setActiveRun: (activeRunId) => set({ activeRunId }),
}));

export function useDashboardFilters() {
  const view = useUiStore((state) => state.view);
  const rangeStart = useUiStore((state) => state.rangeStart);
  const rangeEnd = useUiStore((state) => state.rangeEnd);
  const runId = useUiStore((state) => state.runId);

  return { view, start: rangeStart, end: rangeEnd, runId };
}
