"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { accessEventsUrl } from "@/lib/api";
import { accessToken, authConfigured } from "@/lib/supabase";

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_CEILING_MS = 30_000;

/**
 * Where in the backoff to come back, with the edges taken off.
 *
 * Every tab that lost its stream to the same restart is counting the same
 * doubling from the same moment, so they all return together and the box that
 * just came up meets its whole audience at once. Spreading each one across the
 * second half of its own window costs nobody anything they can notice.
 */
function backoff(attempt: number): number {
  const window = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_CEILING_MS);
  return window / 2 + Math.random() * (window / 2);
}

/**
 * Keeps this tab's idea of its own access, and the people list, current.
 *
 * Approving or removing somebody happens on a different screen from the one
 * that has to change. Polling can only be late, and the two places it mattered
 * were late in opposite directions: a waiting person polled every ten seconds,
 * and somebody already approved did not poll at all — so having their access
 * removed left them clicking around a page that had stopped working, until
 * their next write came back as a raw error.
 *
 * The stream carries a topic name and no data. Everything shown is refetched
 * through the endpoints that check permission, so nothing here can show a
 * reader more than they could already ask for.
 *
 * A stream that never opens is not a failure worth surfacing: the queries keep
 * their slow fallback poll, so this makes the app quicker rather than making
 * it work.
 */
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
      // Uncapped this becomes a tab hammering a backend that is already having
      // a bad time. Thirty seconds is slower than a person notices and far
      // faster than they would have reloaded.
      timer = setTimeout(open, backoff(attempt));
      attempt += 1;
    };

    const open = () => {
      timer = null;
      if (stopped) return;
      // Nothing to attempt while the browser knows it has no connection, and
      // every attempt made anyway pushes the backoff further out — so the tab
      // that comes back from a tunnel would then sit silent for half a minute
      // having done nothing wrong. The online listener below is the way back.
      if (typeof navigator !== "undefined" && navigator.onLine === false) return;

      void accessToken().then((token) => {
        if (stopped || !token) {
          if (!stopped) reconnect();
          return;
        }

        source = new EventSource(accessEventsUrl(token));

        source.onopen = () => {
          attempt = 0;
        };

        // Named events and the default alike: any nudge means ask again. The
        // alternative is a client that has to know which topics exist, which
        // is a second place to update every time one is added.
        source.onmessage = refresh;
        source.addEventListener("access", refresh);
        source.addEventListener("people", refresh);
        source.addEventListener("sync", refresh);

        // The server ends a connection it has held long enough. That is a
        // planned goodbye rather than a fault, so it does not count against
        // the backoff — coming back slower each time the server tidies up
        // would end with a tab that reconnects twice an hour.
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
