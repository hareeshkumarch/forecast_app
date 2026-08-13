"use client";

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
  // Only true between arming and landing. Outside that window the number is a
  // plain span holding a plain number — which is what the server sends, what a
  // page without JavaScript keeps, and what the count settles back into.
  const [counting, setCounting] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (window.matchMedia(REDUCED_MOTION).matches) return;

    // Already on screen as the page loads — a deep link to the section, or a
    // window tall enough to reach it. The server has painted the finished
    // number by now, so arming would show it, blank it and count it back,
    // which is worse than not counting at all. Leave it alone.
    const box = node.getBoundingClientRect();
    if (box.top < window.innerHeight && box.bottom > 0) return;

    // Armed on mount rather than when the observer fires, so that the number
    // is never seen at its answer and then reset to zero on the way in.
    setShown(0);
    setCounting(true);

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
          else setCounting(false);
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

  if (!counting) {
    return (
      <span ref={ref} data-count-up className={cn("tabular-nums", className)}>
        {shown}
      </span>
    );
  }

  return (
    <span ref={ref} data-count-up className={cn("relative inline-block tabular-nums", className)}>
      {/*
       * The finished number, invisible, holding the box open at exactly the
       * width it will end at. Reserving the space in `ch` instead assumes a
       * digit advance equal to the advance of "0", which tabular figures do
       * not guarantee — and the fraction of a pixel that assumption is out by
       * arrives as layout shift on every frame of the count.
       */}
      <span aria-hidden className="invisible">
        {value}
      </span>
      {/*
       * Left, not right. Right-aligned digits slide leftwards the moment the
       * count gains a digit, which is a real glyph movement and lands as
       * layout shift. Growing rightwards into space the box has already
       * reserved moves nothing: every digit is drawn where it will finish.
       */}
      <span className="absolute inset-0 text-left">{shown}</span>
    </span>
  );
}
