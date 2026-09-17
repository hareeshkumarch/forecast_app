"use client";

import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

const DURATION = 900;

function easeOut(progress: number): number {
  return 1 - (1 - progress) ** 3;
}

export type CountUpProps = {
  value: number;
  className?: string;
};

export function CountUp({ value, className }: CountUpProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState(value);
  const [counting, setCounting] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (window.matchMedia(REDUCED_MOTION).matches) return;

    const box = node.getBoundingClientRect();
    if (box.top < window.innerHeight && box.bottom > 0) return;

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
      <span aria-hidden className="invisible">
        {value}
      </span>
      <span className="absolute inset-0 text-left">{shown}</span>
    </span>
  );
}
