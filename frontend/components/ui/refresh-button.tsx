"use client";

import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/**
 * Refresh, with the one thing that makes refreshing a decision rather than a
 * guess: how old what you are looking at already is.
 *
 * A bare "Refresh" button asks the reader to wonder whether they need it. The
 * age answers that before they click, and it keeps counting while they watch —
 * which is also what tells them the screen is live rather than stuck.
 *
 * While it fetches, the glyph turns and everything else holds still. The
 * screen already has the previous answer on it; replacing the age with
 * "Checking…" reflows the whole header row, and swapping the icon for a
 * spinner says the content went away when it did not.
 */
export function RefreshButton({
  updatedAt,
  isFetching,
  onRefresh,
  label = "Refresh",
  className,
}: {
  /** Epoch milliseconds the data was last known good, or 0 if never. */
  updatedAt: number;
  isFetching: boolean;
  onRefresh: () => void;
  /** What gets refreshed, if "Refresh" alone would be ambiguous on the page. */
  label?: string;
  className?: string;
}) {
  const age = useAge(updatedAt);

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span
        aria-live="polite"
        // Fixed width: the wording steps between "just now" and "12 minutes
        // ago" on its own timer, and without a floor for it the button beside
        // it walks across the header every time it does.
        className="hidden min-w-[112px] text-right text-caption text-text-muted sm:inline tabular-nums"
      >
        {age}
      </span>
      <Button variant="ghost" icon={RefreshCw} loading={isFetching} spin onClick={onRefresh}>
        {label}
      </Button>
    </div>
  );
}

/** Re-renders on its own so the age never sits at "just now" for five minutes. */
function useAge(updatedAt: number): string {
  const [, tick] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => tick((n) => n + 1), TICK_MS);
    return () => clearInterval(timer);
  }, []);

  if (!updatedAt) return "Not loaded yet";

  const seconds = Math.max(0, Math.round((Date.now() - updatedAt) / 1000));
  if (seconds < 45) return "Updated just now";
  if (seconds < 90) return "Updated a minute ago";
  if (seconds < 3600) return `Updated ${Math.round(seconds / 60)} minutes ago`;
  if (seconds < 5400) return "Updated an hour ago";
  if (seconds < 86_400) return `Updated ${Math.round(seconds / 3600)} hours ago`;
  return "Updated over a day ago";
}

//: A minute is the smallest step the wording above can show, so ticking faster
//: would re-render for nothing.
const TICK_MS = 30_000;
