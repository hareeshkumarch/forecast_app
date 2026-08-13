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

  isStreaming: boolean;

  isReconnecting: boolean;

  isPolling: boolean;

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

const MAX_STREAM_ATTEMPTS = 3;
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_CEILING_MS = 8_000;
const POLL_INTERVAL_MS = 2_000;

type Transport = "connecting" | "streaming" | "retrying" | "polling";

function isTerminal(status: ForecastProgressEvent["status"]): boolean {
  return status === "completed" || status === "failed";
}

export function useForecastProgress(
  runId: string | null,
  onComplete?: (event: ForecastProgressEvent) => void,
): ForecastProgress {
  const [state, setState] = useState<ForecastProgress>(IDLE);

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
    const controller = new AbortController();

    function teardown() {
      controller.abort();
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
          apply(await getForecastProgress(id, controller.signal), "polling");
        } catch {
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
          const event = JSON.parse(message.data) as ForecastProgressEvent;
          if (apply(event, "streaming")) {
            attempts = 0;
            currentTransport = "streaming";
          }
        } catch {
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

    void Promise.resolve(getForecastProgress(id, controller.signal))
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
