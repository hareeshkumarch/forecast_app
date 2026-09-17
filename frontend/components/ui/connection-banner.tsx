"use client";

import { CloudOff } from "lucide-react";
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

export function ConnectionBanner() {
  const client = useQueryClient();
  const [offline, setOffline] = useState(false);

  useEffect(() => {
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
