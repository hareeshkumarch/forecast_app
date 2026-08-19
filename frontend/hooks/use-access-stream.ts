"use client";

import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { accessEventsUrl } from "@/lib/api";
import { accessToken, authConfigured } from "@/lib/supabase";

const RECONNECT_BASE_MS = 1_000;
const RECONNECT_CEILING_MS = 30_000;

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

    const reconnect = () => {
      if (stopped) return;
      // Uncapped this becomes a tab hammering a backend that is already having
      // a bad time. Thirty seconds is slower than a person notices and far
      // faster than they would have reloaded.
      const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_CEILING_MS);
      attempt += 1;
      timer = setTimeout(open, delay);
    };

    const open = () => {
      if (stopped) return;
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

        source.onerror = () => {
          source?.close();
          source = null;
          reconnect();
        };
      });
    };

    open();

    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
      source?.close();
    };
  }, [client, enabled]);
}
