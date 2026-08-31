"use client";

import { useEffect, useRef, useState } from "react";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

/**
 * How far down the page you are, as a hairline across the top.
 *
 * The nav already answers "which section am I in" with its moving indicator.
 * This answers a different question — "how much of this is left" — which on a
 * page seven sections long is the one that decides whether somebody keeps
 * going. Two indicators would be redundant if they said the same thing; these
 * do not.
 *
 * Driven by `scaleX` on a fixed 1px element, so every frame is a compositor
 * transform: no layout, no paint, nothing that can contend with the reveal
 * transitions running below it. The listener is passive and the write is
 * deferred to a frame, so a fast scroll coalesces into one update per paint
 * rather than one per event.
 *
 * Rendered only after mount and never under reduced motion, which is also why
 * it cannot shift anything: it is fixed, one pixel tall, and outside the flow.
 */
export function ScrollProgress() {
  const [enabled, setEnabled] = useState(false);
  const barRef = useRef<HTMLDivElement>(null);
  const frame = useRef(0);

  useEffect(() => {
    if (window.matchMedia(REDUCED_MOTION).matches) return;
    setEnabled(true);
  }, []);

  useEffect(() => {
    if (!enabled) return;

    const write = () => {
      frame.current = 0;
      const bar = barRef.current;
      if (!bar) return;
      const scrollable = document.documentElement.scrollHeight - window.innerHeight;
      // A page shorter than its viewport has no progress to report, and
      // dividing by zero here would paint a full bar on a page nobody has
      // scrolled.
      const ratio = scrollable > 0 ? window.scrollY / scrollable : 0;
      bar.style.transform = `scaleX(${Math.min(Math.max(ratio, 0), 1)})`;
    };

    const onScroll = () => {
      if (frame.current) return;
      frame.current = requestAnimationFrame(write);
    };

    write();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [enabled]);

  if (!enabled) return null;

  return (
    <div className="scroll-progress" aria-hidden>
      <div ref={barRef} className="scroll-progress-bar" />
    </div>
  );
}
