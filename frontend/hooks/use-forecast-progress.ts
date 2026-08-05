"use client";

import { useEffect, useRef, useState } from "react";

import { forecastEventsUrl, getForecastProgress } from "@/lib/api";
import type { ForecastProgressEvent } from "@/types/api";

export interface ForecastProgress {
  status: ForecastProgressEvent["status"] | "idle";
  progress: number;
  stage: string;
  message: string | null;
  error: string | null;
  /** The stream is open and delivering frames. */
  isStreaming: boolean;
  /** The stream dropped and a bounded reconnect attempt is in progress. */
  isReconnecting: boolean;
  /** Live streaming is unavailable, so the recoverable status endpoint is in use. */
  isPolling: boolean;
  /** Client time of the newest accepted status frame. */
  lastUpdatedAt: number | null;
}

const IDLE: ForecastProgress = {
  status: "idle",
  progress: 0,
  stage: "",
  message: null,
  error: null,
  isStreaming: false,
  isReconnecting: false,
  isPolling: false,
  lastUpdatedAt: null,
};

/** After this many failed attempts, stop reconnecting and poll instead. */
const MAX_STREAM_ATTEMPTS = 3;
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_CEILING_MS = 8_000;
const POLL_INTERVAL_MS = 2_000;

type Transport = "connecting" | "streaming" | "retrying" | "polling";

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
    setState({ ...IDLE, status: "pending", stage: "queued" });

    let done = false;
    let attempts = 0;
    let newestFrame = 0;
    let newestSignature = "";
    let currentTransport: Transport = "connecting";
    let pollInFlight = false;
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

    function apply(event: ForecastProgressEvent, transport: Transport): boolean {
      if (done) return false;
      const signature =
        event.updated_at ??
        [event.status, event.progress, event.stage, event.message, event.error].join(":");
      if (signature === newestSignature) return false;
      const parsed = event.updated_at ? Date.parse(event.updated_at) : Number.NaN;
      const frameTime = Number.isNaN(parsed) ? Date.now() : parsed;
      // Terminal state is authoritative. Hosts can differ slightly in clock
      // time, and that skew must not leave the UI polling a run that finished.
      if (frameTime < newestFrame && !isTerminal(event.status)) return false;
      newestFrame = frameTime;
      newestSignature = signature;

      setState({
        status: event.status,
        progress: event.progress,
        stage: event.stage,
        message: event.message,
        error: event.error,
        isStreaming: !isTerminal(event.status) && transport === "streaming",
        isReconnecting: !isTerminal(event.status) && transport === "retrying",
        isPolling: !isTerminal(event.status) && transport === "polling",
        lastUpdatedAt: frameTime,
      });
      if (isTerminal(event.status)) settle(event);
      return true;
    }

    function startPolling() {
      if (pollTimer || done) return;

      currentTransport = "polling";
      setState((previous) => ({
        ...previous,
        isStreaming: false,
        isReconnecting: false,
        isPolling: true,
      }));

      const check = async () => {
        if (done || pollInFlight) return;
        pollInFlight = true;
        try {
          apply(await getForecastProgress(id), "polling");
        } catch {
          // The API is unreachable too; keep trying on the interval.
        } finally {
          pollInFlight = false;
        }
      };

      void check();
      pollTimer = setInterval(() => void check(), POLL_INTERVAL_MS);
    }

    function connect() {
      if (done) return;

      source = new EventSource(forecastEventsUrl(id));
      const openedSource = source;

      source.onopen = () => {
        if (done || source !== openedSource) return;
        currentTransport = "streaming";
        setState((previous) => ({ ...previous, isStreaming: true, isReconnecting: false }));
      };

      source.onmessage = (message) => {
        if (done || source !== openedSource) return;
        try {
          // A connection is only proven healthy after it delivers a complete
          // frame. Resetting on `open` caused endless one-second reconnects
          // when a proxy accepted the request and immediately closed it.
          const event = JSON.parse(message.data) as ForecastProgressEvent;
          if (apply(event, "streaming")) {
            attempts = 0;
            currentTransport = "streaming";
          }
        } catch {
          // A partial frame is not worth tearing the stream down for.
        }
      };

      source.onerror = () => {
        if (source !== openedSource) return;
        openedSource.close();
        source = null;
        if (done) return;

        attempts += 1;
        if (attempts > MAX_STREAM_ATTEMPTS) {
          startPolling();
          return;
        }

        currentTransport = "retrying";
        setState((previous) => ({ ...previous, isStreaming: false, isReconnecting: true }));
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** (attempts - 1), RECONNECT_CEILING_MS);
        reconnectTimer = setTimeout(connect, delay);
      };
    }

    // Reconcile immediately as well as opening the stream. This recovers a
    // terminal event missed while the tab was sleeping and gives the first
    // paint a durable Celery snapshot after an API restart.
    void Promise.resolve(getForecastProgress(id))
      .then((event) => {
        if (event && newestFrame === 0) apply(event, currentTransport);
      })
      .catch(() => undefined);
    connect();
    return () => {
      done = true;
      teardown();
    };
  }, [runId]);

  return state;
}

export const STAGE_LABELS: Record<string, string> = {
  queued: "Queued",
  aggregating: "Aggregating series",
  backtesting: "Backtesting candidate models",
  fitting: "Fitting the selected model",
  building_outputs: "Building forecast outputs",
  fitting_series: "Forecasting grouped series",
  persisting: "Storing results",
  generating_insights: "Generating insights",
  storing_series: "Storing grouped results",
  complete: "Complete",
  failed: "Failed",
  cancelled: "Cancelled",
};
