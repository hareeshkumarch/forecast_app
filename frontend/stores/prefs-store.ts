"use client";

import { create } from "zustand";

export type ThemeChoice = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";
export type Density = "comfortable" | "compact";

export const PREFS_STORAGE_KEY = "forecast_hub_prefs";

interface StoredPrefs {
  theme: ThemeChoice;
  density: Density;
  sidebarCollapsed: boolean;
  insightsCollapsed: boolean;
}

const DEFAULTS: StoredPrefs = {
  theme: "system",
  density: "comfortable",
  sidebarCollapsed: false,
  insightsCollapsed: false,
};

export function readPrefs(): StoredPrefs {
  if (typeof window === "undefined") return DEFAULTS;

  try {
    const raw = window.localStorage.getItem(PREFS_STORAGE_KEY);
    if (!raw) return DEFAULTS;

    const parsed = JSON.parse(raw) as Partial<StoredPrefs>;
    return {
      theme:
        parsed.theme === "light" || parsed.theme === "dark" || parsed.theme === "system"
          ? parsed.theme
          : DEFAULTS.theme,
      density: parsed.density === "compact" ? "compact" : DEFAULTS.density,
      sidebarCollapsed: parsed.sidebarCollapsed === true,
      insightsCollapsed: parsed.insightsCollapsed === true,
    };
  } catch {
    return DEFAULTS;
  }
}

function writePrefs(prefs: StoredPrefs): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(PREFS_STORAGE_KEY, JSON.stringify(prefs));
  } catch {
  }
}

function systemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function resolveTheme(choice: ThemeChoice): ResolvedTheme {
  return choice === "system" ? systemTheme() : choice;
}

export function applyPrefs(theme: ThemeChoice, density: Density): ResolvedTheme {
  const resolved = resolveTheme(theme);
  if (typeof document !== "undefined") {
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.density = density;
  }
  return resolved;
}

interface PrefsState {
  theme: ThemeChoice;
  density: Density;
  sidebarCollapsed: boolean;
  insightsCollapsed: boolean;
  resolvedTheme: ResolvedTheme;

  hydrated: boolean;
  themeRevision: number;

  setTheme: (theme: ThemeChoice) => void;
  setDensity: (density: Density) => void;
  toggleTheme: () => void;
  toggleSidebar: () => void;
  toggleInsights: () => void;
  hydrate: (force?: boolean) => void;
  syncSystemTheme: () => void;
}

export const usePrefsStore = create<PrefsState>((set, get) => ({
  theme: DEFAULTS.theme,
  density: DEFAULTS.density,
  sidebarCollapsed: DEFAULTS.sidebarCollapsed,
  insightsCollapsed: DEFAULTS.insightsCollapsed,
  resolvedTheme: "light",
  hydrated: false,
  themeRevision: 0,

  setTheme: (theme) => {
    const state = get();
    const { density, sidebarCollapsed, insightsCollapsed } = state;
    const resolvedTheme = applyPrefs(theme, density);
    if (state.theme === theme && state.resolvedTheme === resolvedTheme) return;
    writePrefs({ theme, density, sidebarCollapsed, insightsCollapsed });
    set({
      theme,
      resolvedTheme,
      themeRevision:
        state.themeRevision + (state.resolvedTheme === resolvedTheme ? 0 : 1),
    });
  },

  setDensity: (density) => {
    const state = get();
    if (state.density === density) return;
    const { theme, sidebarCollapsed, insightsCollapsed } = state;
    const resolvedTheme = applyPrefs(theme, density);
    writePrefs({ theme, density, sidebarCollapsed, insightsCollapsed });
    set({ density, resolvedTheme });
  },

  toggleTheme: () => {
    const next: ThemeChoice = get().resolvedTheme === "dark" ? "light" : "dark";
    get().setTheme(next);
  },

  toggleSidebar: () => {
    const { theme, density, sidebarCollapsed, insightsCollapsed } = get();
    const next = !sidebarCollapsed;
    writePrefs({ theme, density, sidebarCollapsed: next, insightsCollapsed });
    set({ sidebarCollapsed: next });
  },

  toggleInsights: () => {
    const { theme, density, sidebarCollapsed, insightsCollapsed } = get();
    const next = !insightsCollapsed;
    writePrefs({ theme, density, sidebarCollapsed, insightsCollapsed: next });
    set({ insightsCollapsed: next });
  },

  hydrate: (force = false) => {
    const state = get();
    if (state.hydrated && !force) return;
    const stored = readPrefs();
    const resolvedTheme = applyPrefs(stored.theme, stored.density);
    set({
      ...stored,
      hydrated: true,
      resolvedTheme,
      themeRevision:
        state.themeRevision + (state.resolvedTheme === resolvedTheme ? 0 : 1),
    });
  },

  syncSystemTheme: () => {
    const { theme, density } = get();
    if (theme !== "system") return;
    const resolvedTheme = applyPrefs(theme, density);
    const state = get();
    if (state.resolvedTheme === resolvedTheme) return;
    set({ resolvedTheme, themeRevision: state.themeRevision + 1 });
  },
}));

export function useThemeRevision(): number {
  return usePrefsStore((state) => state.themeRevision);
}
