"use client";

import { RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

export function RefreshButton({
  updatedAt,
  isFetching,
  onRefresh,
  label = "Refresh",
  className,
}: {
  updatedAt: number;
  isFetching: boolean;
  onRefresh: () => void;

  label?: string;
  className?: string;
}) {
  const age = useAge(updatedAt);

  return (
    <div className={cn("flex items-center gap-2", className)}>
      <span
        aria-live="polite"

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

const TICK_MS = 30_000;
