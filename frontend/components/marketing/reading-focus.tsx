"use client";

import { useEffect, type RefObject } from "react";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

/**
 * Marks whichever child is crossing the reader's line as `data-focus`.
 *
 * The feature rows were the flattest thing on the page: three sentences that
 * faded in once and were then furniture for the rest of the visit. This gives
 * them something to do while they are being read, without touching the type —
 * only the rule and the index answer, so nothing that has to be legible is
 * ever dimmed to make the effect work.
 *
 * The attribute is written straight to the node rather than held in state:
 * this fires on scroll, and re-rendering the section to move an accent one row
 * down is a re-render nobody asked for.
 */
export function useReadingFocus(container: RefObject<HTMLElement>, selector: string): void {
  useEffect(() => {
    const root = container.current;
    if (!root) return;
    if (window.matchMedia(REDUCED_MOTION).matches) return;

    const rows = [...root.querySelectorAll<HTMLElement>(selector)];
    if (!rows.length) return;

    let focused: HTMLElement | null = null;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const row = entry.target as HTMLElement;
          if (row === focused) continue;
          if (focused) delete focused.dataset.focus;
          focused = row;
          row.dataset.focus = "true";
        }
      },
      // A band across the middle of the window, so exactly one row is inside
      // it at a time and the mark moves as the reader moves rather than as
      // sections arrive.
      { rootMargin: "-45% 0px -45% 0px", threshold: 0 },
    );

    rows.forEach((row) => observer.observe(row));
    return () => {
      observer.disconnect();
      if (focused) delete focused.dataset.focus;
    };
  }, [container, selector]);
}
