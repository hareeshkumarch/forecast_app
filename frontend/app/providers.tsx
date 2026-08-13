"use client";

import * as Tooltip from "@radix-ui/react-tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
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

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => {
              if (error instanceof ApiError && !error.isRetryable) return false;
              return failureCount < 2;
            },
          },
          mutations: { retry: false },
        },
      }),
  );

  return (
    <QueryClientProvider client={client}>
      <PreferencesBridge />

      <Tooltip.Provider delayDuration={250} skipDelayDuration={80}>
        {children}
      </Tooltip.Provider>
    </QueryClientProvider>
  );
}
