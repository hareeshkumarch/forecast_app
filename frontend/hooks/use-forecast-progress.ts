"use client";

import { useEffect, useRef, useState } from "react";

import { forecastEventsUrl, getForecastRun } from "@/lib/api";
import type { ForecastProgressEvent } from "@/types/api";

export interface ForecastProgress {
  status: ForecastProgressEvent["status"] | "idle";
  progress: number;
  stage: string;
  message: string | null;
  error: string | null;
  /** The stream is open and delivering frames. */
  isStreaming: boolean;
  /** The stream dropped and is being re-established, or polling has taken over. */
  isReconnecting: boolean;
}

const IDLE: ForecastProgress = {
  status: "idle",
  progress: 0,
  stage: "",
  message: null,
  error: null,
  isStreaming: false,
  isReconnecting: false,
};

/** After this many failed attempts, stop reconnecting and poll instead. */
const MAX_STREAM_ATTEMPTS = 4;
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_CEILING_MS = 8_000;
const POLL_INTERVAL_MS = 5_000;

function isTerminal(status: ForecastProgressEvent["status"]): boolean {
  return status === "completed" || status === "failed";
}

/**
 * Follows one run to its end.
 *
 * A fit can take minutes and now runs on a separate worker, so the stream
 * outliving a wifi blip, a redeploy or a proxy that buys its own idle timeout
 * matters: a dropped connection reconnects with backoff, and if the stream
 * cannot be re-established at all the run is polled instead. Either way the
 * caller still hears about completion exactly once.
 */
export function useForecastProgress(
  runId: string | null,
  onComplete?: (event: ForecastProgressEvent) => void,
): ForecastProgress {
  const [state, setState] = useState<ForecastProgress>(IDLE);

  // Held in a ref so a re-render never leaves the stream calling a stale
  // closure, and so changing the callback does not reopen the connection.
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    if (!runId) {
      setState(IDLE);
      return;
    }

    const id = runId;
    setState({ ...IDLE, status: "pending", isStreaming: true, stage: "queued" });

    let done = false;
    let attempts = 0;
    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    function teardown() {
      source?.close();
      source = null;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (pollTimer) clearInterval(pollTimer);
      reconnectTimer = null;
      pollTimer = null;
    }

    function settle(event: ForecastProgressEvent) {
      if (done) return;
      done = true;
      teardown();
      onCompleteRef.current?.(event);
    }

    function apply(event: ForecastProgressEvent) {
      setState({
        status: event.status,
        progress: event.progress,
        stage: event.stage,
        message: event.message,
        error: event.error,
        isStreaming: !isTerminal(event.status),
        isReconnecting: false,
      });
      if (isTerminal(event.status)) settle(event);
    }

    function startPolling() {
      if (pollTimer || done) return;

      setState((previous) => ({ ...previous, isStreaming: false, isReconnecting: true }));

      const check = async () => {
        if (done) return;
        try {
          const run = await getForecastRun(id);
          apply({
            run_id: run.id,
            status: run.status,
            progress: run.progress,
            stage: run.stage,
            message: null,
            selected_model: run.selected_model,
            error: run.error_message,
          });
        } catch {
          // The API is unreachable too; keep trying on the interval.
        }
      };

      void check();
      pollTimer = setInterval(() => void check(), POLL_INTERVAL_MS);
    }

    function connect() {
      if (done) return;

      source = new EventSource(forecastEventsUrl(id));

      source.onopen = () => {
        attempts = 0;
        setState((previous) => ({ ...previous, isStreaming: true, isReconnecting: false }));
      };

      source.onmessage = (message) => {
        try {
          apply(JSON.parse(message.data) as ForecastProgressEvent);
        } catch {
          // A partial frame is not worth tearing the stream down for.
        }
      };

      source.onerror = () => {
        source?.close();
        source = null;
        if (done) return;

        attempts += 1;
        if (attempts > MAX_STREAM_ATTEMPTS) {
          startPolling();
          return;
        }

        setState((previous) => ({ ...previous, isStreaming: false, isReconnecting: true }));
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** (attempts - 1), RECONNECT_CEILING_MS);
        reconnectTimer = setTimeout(connect, delay);
      };
    }

    connect();
    return teardown;
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
  cancelled: "Cancelled",
};
