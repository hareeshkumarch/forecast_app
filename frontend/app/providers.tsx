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

function retryDelay(attempt: number, error: unknown): number {
  if (error instanceof ApiError && error.retryAfterMs !== null) {
    return Math.max(error.retryAfterMs, RETRY_BASE_MS);
  }
  return Math.min(RETRY_BASE_MS * 2 ** attempt, RETRY_CEILING_MS);
}

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
