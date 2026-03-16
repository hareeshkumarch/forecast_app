import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, X } from "lucide-react";
import { useState } from "react";

export function MlHealthBanner() {
  const [dismissed, setDismissed] = useState(false);
  const { data } = useQuery<{ status?: string; ml_engine?: { status?: string; error?: string } }>({
    queryKey: ["/api/health"],
    refetchInterval: 30_000,
    staleTime: 10_000,
  });

  const mlOk = data?.ml_engine?.status !== "unavailable";
  const show = !dismissed && data && !mlOk;

  if (!show) return null;

  return (
    <div
      role="alert"
      className="flex items-center justify-between gap-4 px-4 py-2.5 bg-destructive/10 border-b border-destructive/20 text-destructive"
    >
      <div className="flex items-center gap-2 min-w-0">
        <AlertTriangle className="w-4 h-4 shrink-0" aria-hidden />
        <p className="text-sm font-medium truncate">
          ML engine unavailable. Training and new forecasts may fail. {data?.ml_engine?.error && `(${data.ml_engine.error})`}
        </p>
      </div>
      <button
        type="button"
        onClick={() => setDismissed(true)}
        className="p-1 rounded hover:bg-destructive/20 focus:outline-none focus:ring-2 focus:ring-ring"
        aria-label="Dismiss banner"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
