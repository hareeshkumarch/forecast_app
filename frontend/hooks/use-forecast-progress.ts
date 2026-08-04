"use client";


import { useEffect, useState } from "react";

import { forecastEventsUrl } from "@/lib/api";
import type { ForecastProgressEvent } from "@/types/api";

export interface ForecastProgress {
  status: ForecastProgressEvent["status"] | "idle";
  progress: number;
  stage: string;
  message: string | null;
  error: string | null;
  isStreaming: boolean;
}

const IDLE: ForecastProgress = {
  status: "idle",
  progress: 0,
  stage: "",
  message: null,
  error: null,
  isStreaming: false,
};

export function useForecastProgress(
  runId: string | null,
  onComplete?: (event: ForecastProgressEvent) => void,
): ForecastProgress {
  const [state, setState] = useState<ForecastProgress>(IDLE);

  useEffect(() => {
    if (!runId) {
      setState(IDLE);
      return;
    }

    setState({ ...IDLE, status: "pending", isStreaming: true, stage: "queued" });

    const source = new EventSource(forecastEventsUrl(runId));
    let settled = false;

    source.onmessage = (message) => {
      let event: ForecastProgressEvent;
      try {
        event = JSON.parse(message.data) as ForecastProgressEvent;
      } catch {
        return;
      }

      setState({
        status: event.status,
        progress: event.progress,
        stage: event.stage,
        message: event.message,
        error: event.error,
        isStreaming: event.status === "pending" || event.status === "running",
      });

      if (event.status === "completed" || event.status === "failed") {
        settled = true;
        source.close();
        onComplete?.(event);
      }
    };

    source.onerror = () => {
      
      
      if (settled) return;
      source.close();
      setState((previous) => ({
        ...previous,
        isStreaming: false,
        error: "Lost connection to the progress stream.",
      }));
    };

    return () => {
      source.close();
    };
    
    
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  return state;
}

export const STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  aggregating: "Aggregating series",
  backtesting: "Backtesting candidate models",
  fitting: "Fitting the selected model",
  persisting: "Storing results",
  generating_insights: "Generating insights",
  complete: "Complete",
  failed: "Failed",
};
