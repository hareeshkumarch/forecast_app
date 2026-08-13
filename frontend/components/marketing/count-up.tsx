"use client";

import type { CSSProperties } from "react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

const DURATION = 900;

/** Quick off the mark, then settling — the last few digits are readable
 *  rather than a blur that stops dead on the answer. */
function easeOut(progress: number): number {
  return 1 - (1 - progress) ** 3;
}

export type CountUpProps = {
  value: number;
  className?: string;
};

/**
 * Counts up to `value` the first time it is scrolled into view.
 *
 * The finished number is what renders on the server, and what keeps rendering
 * with no JavaScript or under a reduced-motion preference. The count is an
 * emphasis on a number that is already there — never the only way to read it.
 */
export function CountUp({ value, className }: CountUpProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState(value);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (window.matchMedia(REDUCED_MOTION).matches) return;

    // Armed on mount rather than when the observer fires. The section this
    // sits in is several screens down, so this always happens long before it
    // is on screen, and the number is never seen at its answer and then reset.
    setShown(0);

    let frame = 0;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        observer.disconnect();

        const started = performance.now();
        const tick = (now: number) => {
          const progress = Math.min((now - started) / DURATION, 1);
          setShown(Math.round(easeOut(progress) * value));
          if (progress < 1) frame = requestAnimationFrame(tick);
        };
        frame = requestAnimationFrame(tick);
      },
      { threshold: 0.6 },
    );

    observer.observe(node);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [value]);

  return (
    <span
      ref={ref}
      // Held at the width of the finished number: with tabular figures `ch` is
      // exactly one digit, so the count cannot push the sentence around it.
      className={cn("inline-block text-right tabular-nums", className)}
      style={{ minWidth: `${String(value).length}ch` } as CSSProperties}
    >
      {shown}
    </span>
  );
}
