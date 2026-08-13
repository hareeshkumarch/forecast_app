"use client";

import { create } from "zustand";
import { useShallow } from "zustand/react/shallow";

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

const WORKSPACE_STORAGE_KEY = "forecast_hub_workspace";

interface StoredWorkspace {
  view: ForecastView;
  rangeStart: string | null;
  rangeEnd: string | null;
  runId: string | null;
}

const DEFAULT_WORKSPACE: StoredWorkspace = {
  view: "base",
  rangeStart: null,
  rangeEnd: null,
  runId: null,
};

function storedDate(value: unknown): string | null {
  return typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null;
}

function storedRunId(value: unknown): string | null {
  return typeof value === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value)
    ? value
    : null;
}

function readWorkspace(): StoredWorkspace | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(WORKSPACE_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<StoredWorkspace>;
    return {
      view: parsed.view === "best" || parsed.view === "worst" ? parsed.view : "base",
      rangeStart: storedDate(parsed.rangeStart),
      rangeEnd: storedDate(parsed.rangeEnd),
      runId: storedRunId(parsed.runId),
    };
  } catch {
    return null;
  }
}

function writeWorkspace(workspace: StoredWorkspace): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(WORKSPACE_STORAGE_KEY, JSON.stringify(workspace));
  } catch {
  }
}

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
  hydrateWorkspace: () => void;
  resetDashboardFilters: () => void;
}

export const useUiStore = create<UiState>((set, get) => ({
  ...DEFAULT_WORKSPACE,

  modal: "none",
  modalTargetId: null,
  insightDrawer: null,
  mobileRail: null,
  activeRunId: null,

  setView: (view) => {
    const state = get();
    if (state.view === view) return;
    writeWorkspace({
      view,
      rangeStart: state.rangeStart,
      rangeEnd: state.rangeEnd,
      runId: state.runId,
    });
    set({ view });
  },
  setRange: (rangeStart, rangeEnd) => {
    const state = get();
    if (state.rangeStart === rangeStart && state.rangeEnd === rangeEnd) return;
    writeWorkspace({ view: state.view, rangeStart, rangeEnd, runId: state.runId });
    set({ rangeStart, rangeEnd });
  },
  setRunId: (runId) => {
    const state = get();
    if (state.runId === runId) return;
    writeWorkspace({
      view: state.view,
      rangeStart: state.rangeStart,
      rangeEnd: state.rangeEnd,
      runId,
    });
    set({ runId });
  },

  openModal: (modal, modalTargetId = null) =>
    set({ modal, modalTargetId, mobileRail: null, insightDrawer: null }),
  closeModal: () => {
    const state = get();
    if (state.modal === "none" && state.modalTargetId === null) return;
    set({ modal: "none", modalTargetId: null });
  },

  openInsight: (insightDrawer) =>
    set({
      insightDrawer,
      mobileRail: null,
      modal: "none",
      modalTargetId: null,
    }),
  closeInsight: () => {
    if (get().insightDrawer === null) return;
    set({ insightDrawer: null });
  },

  openRail: (mobileRail) =>
    set({
      mobileRail,
      modal: "none",
      modalTargetId: null,
      insightDrawer: null,
    }),
  closeRail: () => {
    if (get().mobileRail === null) return;
    set({ mobileRail: null });
  },

  setActiveRun: (activeRunId) => {
    if (get().activeRunId === activeRunId) return;
    set({ activeRunId });
  },

  hydrateWorkspace: () => {
    const stored = readWorkspace();
    if (!stored) return;
    const state = get();
    if (
      state.view === stored.view &&
      state.rangeStart === stored.rangeStart &&
      state.rangeEnd === stored.rangeEnd &&
      state.runId === stored.runId
    ) return;
    set(stored);
  },

  resetDashboardFilters: () => {
    const state = get();
    if (
      state.view === DEFAULT_WORKSPACE.view &&
      state.rangeStart === null &&
      state.rangeEnd === null &&
      state.runId === null
    ) return;
    writeWorkspace(DEFAULT_WORKSPACE);
    set(DEFAULT_WORKSPACE);
  },
}));

export function useDashboardFilters() {
  return useUiStore(
    useShallow((state) => ({
      view: state.view,
      start: state.rangeStart,
      end: state.rangeEnd,
      runId: state.runId,
    })),
  );
}
