"use client";

import { useEffect, useState } from "react";

/**
 * A value that waits for the typing to stop.
 *
 * Search moved from the browser to the database when the lists grew past what
 * it was safe to hold in memory, which turned every keystroke into a request
 * over several ILIKEs. This spends one request per pause instead of one per
 * letter; the screen still updates as fast as anyone reads it.
 */
export function useDebounced<T>(value: T, delayMs = 250): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return settled;
}
