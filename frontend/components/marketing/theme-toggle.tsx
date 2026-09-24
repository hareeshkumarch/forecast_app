"use client";

import { Moon, Sun } from "lucide-react";

import { usePrefsStore } from "@/stores/prefs-store";

export function ThemeToggle() {
  const toggleTheme = usePrefsStore((state) => state.toggleTheme);

  return (
    <button
      type="button"
      onClick={toggleTheme}
      title="Switch between light and dark"
      aria-label="Switch between light and dark"
      className="nav-control inline-flex size-10 shrink-0 items-center justify-center border border-land-rule bg-surface text-text-primary transition-colors hover:border-text-muted hover:bg-surface-muted"
    >
      <Sun className="theme-icon-light size-[18px]" strokeWidth={1.8} aria-hidden />
      <Moon className="theme-icon-dark size-[18px]" strokeWidth={1.8} aria-hidden />
    </button>
  );
}
