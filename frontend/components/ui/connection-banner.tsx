"use client";

import { CloudOff } from "lucide-react";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

/**
 * Says out loud that the browser has no connection.
 *
 * Without it the whole app simply stops answering: panels sit on stale
 * numbers, a save reports a failure that sounds like the server's, and the
 * only clue is that everything went quiet at once. Naming it costs one line
 * and turns "the app is broken" into "my wifi dropped".
 *
 * Coming back refetches, because react-query pauses rather than fails while
 * offline and the panels underneath are showing figures from before the gap.
 */
export function ConnectionBanner() {
  const client = useQueryClient();
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    // Read here rather than in the initial state: the server render has no
    // navigator, and seeding from one would make the first client render
    // disagree with the HTML it is hydrating.
    setOffline(navigator.onLine === false);

    const goneOffline = () => setOffline(true);
    const backOnline = () => {
      setOffline(false);
      void client.invalidateQueries();
    };

    window.addEventListener("offline", goneOffline);
    window.addEventListener("online", backOnline);
    return () => {
      window.removeEventListener("offline", goneOffline);
      window.removeEventListener("online", backOnline);
    };
  }, [client]);

  if (!offline) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center gap-2 border-b border-warning-border bg-warning-soft px-4 py-2 text-caption text-text-primary"
    >
      <CloudOff className="h-3.5 w-3.5 shrink-0 text-warning" aria-hidden />
      <span>
        <strong className="font-medium">You are offline.</strong>{" "}
        <span className="text-text-secondary">
          What is on screen is the last thing this tab was told. It picks up on its own as soon as
          the connection is back.
        </span>
      </span>
    </div>
  );
}
