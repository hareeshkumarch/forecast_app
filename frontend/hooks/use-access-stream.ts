"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { accessEventsUrl } from "@/lib/api";
import { accessToken, authConfigured } from "@/lib/supabase";

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_CEILING_MS = 30_000;

function backoff(attempt: number): number {
  const window = Math.min(
    RECONNECT_BASE_MS * 2 ** attempt,
    RECONNECT_CEILING_MS,
  );
  return window / 2 + Math.random() * (window / 2);
}

export function useAccessStream(enabled: boolean) {
  const client = useQueryClient();

  useEffect(() => {
    if (!enabled || !authConfigured) return;

    let source: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;
    let stopped = false;

    const refresh = () => {
      void client.invalidateQueries({ queryKey: ["auth", "me"] });
      void client.invalidateQueries({ queryKey: ["auth", "users"] });
    };

    const close = () => {
      source?.close();
      source = null;
      if (timer) clearTimeout(timer);
      timer = null;
    };

    const reconnect = () => {
      if (stopped || timer) return;
      timer = setTimeout(open, backoff(attempt));
      attempt += 1;
    };

    const open = () => {
      timer = null;
      if (stopped) return;
      if (typeof navigator !== "undefined" && navigator.onLine === false)
        return;

      void accessToken().then((token) => {
        if (stopped || !token) {
          if (!stopped) reconnect();
          return;
        }

        close();
        source = new EventSource(accessEventsUrl(token));

        source.onopen = () => {
          attempt = 0;
        };

        source.onmessage = refresh;
        source.addEventListener("access", refresh);
        source.addEventListener("people", refresh);
        source.addEventListener("sync", refresh);

        source.addEventListener("expired", () => {
          attempt = 0;
          close();
          reconnect();
        });

        source.onerror = () => {
          close();
          reconnect();
        };
      });
    };

    const onOnline = () => {
      attempt = 0;
      close();
      open();
    };
    const onOffline = close;

    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    open();

    return () => {
      stopped = true;
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      close();
    };
  }, [client, enabled]);
}
