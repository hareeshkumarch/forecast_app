

import { create } from "zustand";

import type { ForecastView, Insight } from "@/types/api";

export type ModalKind =
  | "none"
  | "add-connector"
  | "upload-dataset"
  | "configure-forecast"
  | "connector-import";

interface UiState {
  
  view: ForecastView;
  rangeStart: string | null;
  rangeEnd: string | null;
  runId: string | null;
  selectedConnectorId: string | null;

  
  modal: ModalKind;
  modalConnectorId: string | null;
  insightDrawer: Insight | null;

  
  activeRunId: string | null;

  setView: (view: ForecastView) => void;
  setRange: (start: string | null, end: string | null) => void;
  setRunId: (runId: string | null) => void;
  selectConnector: (id: string | null) => void;

  openModal: (modal: ModalKind, connectorId?: string | null) => void;
  closeModal: () => void;

  openInsight: (insight: Insight) => void;
  closeInsight: () => void;

  setActiveRun: (runId: string | null) => void;
}

export const useUiStore = create<UiState>((set) => ({
  view: "base",
  rangeStart: null,
  rangeEnd: null,
  runId: null,
  
  
  selectedConnectorId: null,

  modal: "none",
  modalConnectorId: null,
  insightDrawer: null,
  activeRunId: null,

  setView: (view) => set({ view }),
  setRange: (rangeStart, rangeEnd) => set({ rangeStart, rangeEnd }),
  setRunId: (runId) => set({ runId }),
  selectConnector: (selectedConnectorId) => set({ selectedConnectorId }),

  openModal: (modal, modalConnectorId = null) => set({ modal, modalConnectorId }),
  closeModal: () => set({ modal: "none", modalConnectorId: null }),

  openInsight: (insightDrawer) => set({ insightDrawer }),
  closeInsight: () => set({ insightDrawer: null }),

  setActiveRun: (activeRunId) => set({ activeRunId }),
}));


export function useDashboardFilters() {
  const view = useUiStore((state) => state.view);
  const rangeStart = useUiStore((state) => state.rangeStart);
  const rangeEnd = useUiStore((state) => state.rangeEnd);
  const runId = useUiStore((state) => state.runId);

  return { view, start: rangeStart, end: rangeEnd, runId };
}
