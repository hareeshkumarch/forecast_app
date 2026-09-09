"use client";

import { useEffect } from "react";

import { Mark } from "@/components/marketing/mark";
import { Button } from "@/components/ui/primitives";

/**
 * What a route shows when its render threw and no boundary inside it caught it.
 *
 * Without this file Next renders its own bare screen in production — a
 * centred "Application error: a client-side exception has occurred" on white,
 * no navigation, no way back. This is the same failure with a way out of it.
 */
export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Route render failed", error);
  }, [error]);

  return (
    <main className="flex min-h-[100dvh] flex-col items-center justify-center gap-3 bg-canvas px-6 text-center">
      <Mark size={34} />
      <h1 className="mt-3 text-heading font-semibold tracking-[-0.02em] text-text-primary">
        This page stopped working
      </h1>
      <p className="max-w-[46ch] text-meta leading-relaxed text-text-secondary">
        Nothing you have saved is affected. Trying again reloads just this page; if it keeps
        happening, the reference below is what identifies it in the logs.
      </p>
      {error.digest ? (
        <p className="text-caption text-text-muted">Reference {error.digest}</p>
      ) : null}
      <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
        <Button onClick={reset}>Try again</Button>
        <Button variant="secondary" onClick={() => window.location.assign("/dashboard")}>
          Back to the dashboard
        </Button>
      </div>
    </main>
  );
}
