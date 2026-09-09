"use client";

import * as Tooltip from "@radix-ui/react-tooltip";
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api";
import { PREFS_STORAGE_KEY, usePrefsStore } from "@/stores/prefs-store";
import { useUiStore } from "@/stores/ui-store";

function PreferencesBridge() {
  const hydrate = usePrefsStore((state) => state.hydrate);
  const syncSystemTheme = usePrefsStore((state) => state.syncSystemTheme);
  const hydrateWorkspace = useUiStore((state) => state.hydrateWorkspace);

  useEffect(() => {
    hydrate();
    hydrateWorkspace();

    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => syncSystemTheme();
    const onStorage = (event: StorageEvent) => {
      if (event.key === PREFS_STORAGE_KEY) hydrate(true);
    };
    query.addEventListener("change", onChange);
    window.addEventListener("storage", onStorage);
    return () => {
      query.removeEventListener("change", onChange);
      window.removeEventListener("storage", onStorage);
    };
  }, [hydrate, hydrateWorkspace, syncSystemTheme]);

  return null;
}

const RETRY_BASE_MS = 1_000;
const RETRY_CEILING_MS = 30_000;

/**
 * How long to wait before asking again.
 *
 * A 429 or a 503 names its own delay, and it is the only party that knows:
 * doubling from a second means a client told to wait a minute comes back
 * eleven times before that minute is up, each one refused, each one counted
 * against the limit it is waiting out. Where the server said nothing, the
 * usual backoff.
 */
function retryDelay(attempt: number, error: unknown): number {
  if (error instanceof ApiError && error.retryAfterMs !== null) {
    return Math.max(error.retryAfterMs, RETRY_BASE_MS);
  }
  return Math.min(RETRY_BASE_MS * 2 ** attempt, RETRY_CEILING_MS);
}

/**
 * Access that changed underneath the tab, noticed without being told.
 *
 * The stream normally carries this, and the stream is the thing least likely
 * to be up when it matters — it is the first casualty of a proxy, a sleep, or
 * a restart. A 403 naming an access status is the same news arriving by the
 * other door, so the gate is asked to re-read itself rather than leaving
 * somebody clicking around a page that has quietly stopped working.
 */
function accessMayHaveChanged(error: unknown, client: QueryClient): void {
  if (!(error instanceof ApiError)) return;
  if (error.status !== 403 || !("status" in error.detail)) return;
  void client.invalidateQueries({ queryKey: ["auth", "me"] });
}

function createClient(): QueryClient {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({ onError: (error) => accessMayHaveChanged(error, client) }),
    mutationCache: new MutationCache({ onError: (error) => accessMayHaveChanged(error, client) }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: false,
        retry: (failureCount, error) => {
          if (error instanceof ApiError && !error.isRetryable) return false;
          return failureCount < 2;
        },
        retryDelay,
      },
      mutations: { retry: false },
    },
  });
  return client;
}

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(createClient);

  return (
    <QueryClientProvider client={client}>
      <PreferencesBridge />

      <Tooltip.Provider delayDuration={250} skipDelayDuration={80}>
        {children}
      </Tooltip.Provider>
    </QueryClientProvider>
  );
}
