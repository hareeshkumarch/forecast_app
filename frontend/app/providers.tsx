"use client";

import * as Tooltip from "@radix-ui/react-tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api";
import { usePrefsStore } from "@/stores/prefs-store";

/**
 * Applies stored preferences after hydration and follows the OS setting while
 * the theme is left on "system". The pre-paint script in the layout has
 * already set the attributes, so this only keeps them in sync.
 */
function PreferencesBridge() {
  const hydrate = usePrefsStore((state) => state.hydrate);
  const syncSystemTheme = usePrefsStore((state) => state.syncSystemTheme);

  useEffect(() => {
    hydrate();

    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => syncSystemTheme();
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [hydrate, syncSystemTheme]);

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
      {/* App-wide, so anything can carry a tooltip — including the parts of the
          sidebar that the mobile drawer renders outside the sidebar itself. */}
      <Tooltip.Provider delayDuration={250} skipDelayDuration={80}>
        {children}
      </Tooltip.Provider>
    </QueryClientProvider>
  );
}
