import { beforeEach, describe, expect, it, vi } from "vitest";

import { applyPrefs, readPrefs, resolveTheme, usePrefsStore } from "@/stores/prefs-store";

function stubSystemTheme(dark: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({
      matches: dark,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  );
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-density");
  stubSystemTheme(false);
  usePrefsStore.setState({
    theme: "system",
    density: "comfortable",
    resolvedTheme: "light",
    revision: 0,
  });
});

describe("stored preferences", () => {
  it("defaults to following the system theme", () => {
    expect(readPrefs()).toEqual({ theme: "system", density: "comfortable" });
  });

  it("ignores a corrupted or unknown entry", () => {
    window.localStorage.setItem("forecast_hub_prefs", "{not json");
    expect(readPrefs().theme).toBe("system");

    window.localStorage.setItem("forecast_hub_prefs", JSON.stringify({ theme: "neon" }));
    expect(readPrefs().theme).toBe("system");
  });

  it("round-trips through the store", () => {
    usePrefsStore.getState().setTheme("dark");
    usePrefsStore.getState().setDensity("compact");

    expect(readPrefs()).toEqual({ theme: "dark", density: "compact" });
  });
});

describe("applying preferences", () => {
  it("writes both attributes onto the document element", () => {
    applyPrefs("dark", "compact");

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.density).toBe("compact");
  });

  it("resolves the system choice against the OS setting", () => {
    stubSystemTheme(true);
    expect(resolveTheme("system")).toBe("dark");

    stubSystemTheme(false);
    expect(resolveTheme("system")).toBe("light");

    expect(resolveTheme("dark")).toBe("dark");
  });
});

describe("theme toggling", () => {
  it("flips the resolved theme and bumps the revision so charts repaint", () => {
    const before = usePrefsStore.getState().revision;

    usePrefsStore.getState().setTheme("light");
    usePrefsStore.getState().toggleTheme();

    const state = usePrefsStore.getState();
    expect(state.resolvedTheme).toBe("dark");
    expect(state.theme).toBe("dark");
    expect(state.revision).toBeGreaterThan(before);
  });

  it("leaves an explicit choice alone when the OS changes", () => {
    usePrefsStore.getState().setTheme("light");
    stubSystemTheme(true);

    usePrefsStore.getState().syncSystemTheme();

    expect(usePrefsStore.getState().resolvedTheme).toBe("light");
  });
});
