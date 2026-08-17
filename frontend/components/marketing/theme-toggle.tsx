"use client";

import { Moon, Sun } from "lucide-react";

import { usePrefsStore } from "@/stores/prefs-store";

/**
 * Light and dark, from the landing page.
 *
 * The same store the dashboard's header writes to, so the choice a visitor
 * makes here is the one waiting for them inside the product, and the reverse.
 *
 * Which icon shows is decided in CSS from `data-theme` on the document, not
 * from the store. The theme is set by the bootstrap script in `app/layout.tsx`
 * before the first paint, while the store still reads "light" until it
 * hydrates — so a button rendered from the store shows a sun to someone whose
 * page is already dark, for as long as it takes React to arrive. The label
 * says what the button does rather than what the theme currently is, for the
 * same reason: it is the one sentence that is true either way.
 */
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
