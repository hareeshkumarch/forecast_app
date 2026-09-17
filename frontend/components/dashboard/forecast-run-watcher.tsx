"use client";

import { CheckCircle2, ChevronRight, Clock, Loader2, TriangleAlert, X } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useRef, type ReactNode } from "react";

import { useRefreshDashboard } from "@/hooks/use-dashboard";
import { type ForecastProgress, useForecastProgress } from "@/hooks/use-forecast-progress";
import { humanizeModel } from "@/lib/format";
import { cn } from "@/lib/utils";
import { toast } from "@/stores/toast-store";
import { useUiStore } from "@/stores/ui-store";

const IDLE: ForecastProgress = {
  status: "idle",
  progress: 0,
  stage: "",
  message: null,
  error: null,
  queueAhead: null,
  hasQueued: false,
  isStreaming: false,
  isReconnecting: false,
  isPolling: false,
  lastUpdatedAt: null,
};

const ForecastProgressContext = createContext<ForecastProgress>(IDLE);

export function useActiveForecastProgress(): ForecastProgress {
  return useContext(ForecastProgressContext);
}

export function ForecastRunProvider({ children }: { children: ReactNode }) {
  const activeRunId = useUiStore((state) => state.activeRunId);
  const setRunId = useUiStore((state) => state.setRunId);
  const closeModal = useUiStore((state) => state.closeModal);
  const refreshDashboard = useRefreshDashboard();
  const router = useRouter();
  const pathname = usePathname();

  const pathnameRef = useRef(pathname);
  pathnameRef.current = pathname;

  const progress = useForecastProgress(activeRunId, (event) => {
    useUiStore.getState().finishActiveRun();

    if (event.status === "completed") {
      setRunId(event.run_id);
      refreshDashboard();

      const winner = event.selected_model
        ? `${humanizeModel(event.selected_model)} won the backtest.`
        : "The dashboard now reflects this run.";

      toast.action(
        "success",
        "Forecast complete",
        {
          label: pathnameRef.current === "/dashboard" ? "See the numbers" : "View forecast",
          onClick: () => {
            closeModal();
            if (pathnameRef.current !== "/dashboard") router.push("/dashboard");
          },
        },
        winner,
      );
      return;
    }

    if (event.status === "failed") {
      if (event.stage === "cancelled") {
        toast.info("Forecast cancelled", "No more model work will be started for this run.");
        return;
      }
      toast.action(
        "error",
        "Forecast failed",
        { label: "Show details", onClick: () => useUiStore.getState().openModal("configure-forecast") },
        event.error ?? "The run did not finish.",
      );
    }
  });

  useTabTitleProgress(progress);

  return (
    <ForecastProgressContext.Provider value={progress}>
      {children}
    </ForecastProgressContext.Provider>
  );
}

function useTabTitleProgress(progress: ForecastProgress): void {
  const original = useRef<string | null>(null);

  useEffect(() => {
    if (typeof document === "undefined") return;
    original.current ??= document.title;
    const base = original.current;

    const paint = () => {
      if (progress.status === "idle") {
        document.title = base;
        return;
      }
      if (!document.hidden) {
        document.title = base;
        return;
      }
      if (progress.status === "completed") document.title = `✓ Forecast ready — ${base}`;
      else if (progress.status === "failed") document.title = `⚠ Forecast failed — ${base}`;
      else if (progress.queueAhead !== null) document.title = `⏳ Queued — ${base}`;
      else document.title = `(${Math.round(progress.progress * 100)}%) ${base}`;
    };

    paint();
    document.addEventListener("visibilitychange", paint);
    return () => {
      document.removeEventListener("visibilitychange", paint);
      document.title = base;
    };
  }, [progress.status, progress.progress, progress.queueAhead]);
}

export function ForecastRunPill() {
  const activeRunId = useUiStore((state) => state.activeRunId);
  const modal = useUiStore((state) => state.modal);
  const openModal = useUiStore((state) => state.openModal);
  const setActiveRun = useUiStore((state) => state.setActiveRun);
  const progress = useActiveForecastProgress();

  if (!activeRunId || modal === "configure-forecast") return null;

  const done = progress.status === "completed";
  const failed = progress.status === "failed";
  const percent = Math.round(progress.progress * 100);
  const queued = progress.queueAhead !== null;

  return (
    <div
      className={cn(
        "fixed bottom-3 left-3 z-40 flex items-center gap-1 rounded-card border shadow-popover",
        "bg-surface pl-1 pr-1 text-caption",
        failed ? "border-negative-border" : done ? "border-positive-border" : "border-border",
      )}
      role="status"
    >
      <button
        type="button"
        onClick={() => openModal("configure-forecast")}
        className="flex min-h-9 items-center gap-2 rounded-input px-2 transition-colors duration-fast hover:bg-surface-muted"
      >
        {done ? (
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-positive" aria-hidden />
        ) : failed ? (
          <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-negative" aria-hidden />
        ) : queued ? (
          <Clock className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden />
        ) : (
          <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-accent" aria-hidden />
        )}
        <span className="font-medium text-text-primary">
          {done
            ? "Forecast ready"
            : failed
              ? "Forecast failed"
              : queued
                ? progress.queueAhead === 0
                  ? "Queued — next in line"
                  : `Queued — ${progress.queueAhead} ahead`
                : `Forecasting… ${percent}%`}
        </span>
        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-text-muted" aria-hidden />
      </button>

      <span aria-live="polite" className="sr-only">
        {done ? "Forecast complete." : failed ? "Forecast failed." : ""}
      </span>

      {done || failed ? (
        <button
          type="button"
          aria-label="Dismiss"
          onClick={() => setActiveRun(null)}
          className="mr-0.5 rounded-input p-1.5 text-text-muted transition-colors duration-fast hover:bg-surface-muted hover:text-text-primary"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      ) : null}
    </div>
  );
}
