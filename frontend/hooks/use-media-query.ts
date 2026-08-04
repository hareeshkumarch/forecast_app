"use client";

import { useEffect, useState } from "react";

/** The widths the two rails become inline at, shared by everything that cares. */
export const RAIL_MEDIA = {
  navigation: "(min-width: 1024px)",
  insights: "(min-width: 1720px)",
} as const;

/**
 * Tracks a CSS media query from React. Starts false on the server and on the
 * first client render, so markup matches and hydration stays quiet; the real
 * value lands in the effect immediately after.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const media = window.matchMedia(query);
    setMatches(media.matches);

    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}
