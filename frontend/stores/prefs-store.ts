"use client";

import { create } from "zustand";

export type ThemeChoice = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";
export type Density = "comfortable" | "compact";

const STORAGE_KEY = "forecast_hub_prefs";

interface StoredPrefs {
  theme: ThemeChoice;
  density: Density;
  sidebarCollapsed: boolean;
}

const DEFAULTS: StoredPrefs = { theme: "system", density: "comfortable", sidebarCollapsed: false };

export function readPrefs(): StoredPrefs {
  if (typeof window === "undefined") return DEFAULTS;

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;

    const parsed = JSON.parse(raw) as Partial<StoredPrefs>;
    return {
      theme:
        parsed.theme === "light" || parsed.theme === "dark" || parsed.theme === "system"
          ? parsed.theme
          : DEFAULTS.theme,
      density: parsed.density === "compact" ? "compact" : DEFAULTS.density,
      sidebarCollapsed: parsed.sidebarCollapsed === true,
    };
  } catch {
    return DEFAULTS;
  }
}

function writePrefs(prefs: StoredPrefs): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
  } catch {
    // A browser with storage disabled still themes correctly for this session.
  }
}

export function systemTheme(): ResolvedTheme {
  if (typeof window === "undefined") return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function resolveTheme(choice: ThemeChoice): ResolvedTheme {
  return choice === "system" ? systemTheme() : choice;
}

/**
 * The document element carries the theme and density, so CSS variables — and
 * anything reading them, including the charts — update in one place.
 */
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
  resolvedTheme: ResolvedTheme;
  /** Bumped on every applied change, so chart options can be recomputed. */
  revision: number;

  setTheme: (theme: ThemeChoice) => void;
  setDensity: (density: Density) => void;
  toggleTheme: () => void;
  toggleSidebar: () => void;
  hydrate: () => void;
  syncSystemTheme: () => void;
}

export const usePrefsStore = create<PrefsState>((set, get) => ({
  theme: DEFAULTS.theme,
  density: DEFAULTS.density,
  sidebarCollapsed: DEFAULTS.sidebarCollapsed,
  resolvedTheme: "light",
  revision: 0,

  setTheme: (theme) => {
    const { density, sidebarCollapsed } = get();
    const resolvedTheme = applyPrefs(theme, density);
    writePrefs({ theme, density, sidebarCollapsed });
    set((state) => ({ theme, resolvedTheme, revision: state.revision + 1 }));
  },

  setDensity: (density) => {
    const { theme, sidebarCollapsed } = get();
    const resolvedTheme = applyPrefs(theme, density);
    writePrefs({ theme, density, sidebarCollapsed });
    set((state) => ({ density, resolvedTheme, revision: state.revision + 1 }));
  },

  toggleTheme: () => {
    const next: ThemeChoice = get().resolvedTheme === "dark" ? "light" : "dark";
    get().setTheme(next);
  },

  toggleSidebar: () => {
    const { theme, density, sidebarCollapsed } = get();
    const next = !sidebarCollapsed;
    writePrefs({ theme, density, sidebarCollapsed: next });
    // The rails and panels are sized by container queries, so the workspace
    // reflows on its own once the sidebar changes width.
    set((state) => ({ sidebarCollapsed: next, revision: state.revision + 1 }));
  },

  hydrate: () => {
    const stored = readPrefs();
    const resolvedTheme = applyPrefs(stored.theme, stored.density);
    set((state) => ({ ...stored, resolvedTheme, revision: state.revision + 1 }));
  },

  syncSystemTheme: () => {
    const { theme, density } = get();
    if (theme !== "system") return;
    const resolvedTheme = applyPrefs(theme, density);
    set((state) => ({ resolvedTheme, revision: state.revision + 1 }));
  },
}));

/** Chart builders depend on this so a theme change repaints them. */
export function useThemeRevision(): number {
  return usePrefsStore((state) => state.revision);
}
