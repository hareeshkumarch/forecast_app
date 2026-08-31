"use client";

import { useEffect, useRef, useState } from "react";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

/**
 * Publishes how far the hero has scrolled, as a 0–1 custom property.
 *
 * The page had no depth cue at all: every layer moved with the scroll at
 * exactly the same rate, which is what makes a long page feel like one flat
 * sheet being dragged past. Giving the wash, the chart and the headline
 * slightly different rates costs three transforms and buys the sense that
 * there is something behind something else.
 *
 * One listener writing one custom property, rather than a listener per layer:
 * the CSS below decides how far each layer travels, so adding a fourth layer
 * is a line of CSS rather than another subscription. Everything downstream is
 * `translate3d` and `opacity`, so a frame is a compositor pass.
 *
 * Deliberately capped at the hero's own height. Past that the property stops
 * at 1 and the transforms stop moving — a parallax that keeps going after its
 * section has left is how elements end up drifting into the one below.
 */
export function ScrollDepth({ target }: { target: string }) {
  const [enabled, setEnabled] = useState(false);
  const frame = useRef(0);

  useEffect(() => {
    if (window.matchMedia(REDUCED_MOTION).matches) return;
    setEnabled(true);
  }, []);

  useEffect(() => {
    if (!enabled) return;
    const node = document.querySelector<HTMLElement>(target);
    if (!node) return;

    const write = () => {
      frame.current = 0;
      // The hero's own height is the travel, so the effect is the same
      // fraction of the section on a phone as on a desktop.
      const span = Math.max(node.offsetHeight, 1);
      const progress = Math.min(Math.max(window.scrollY / span, 0), 1);
      node.style.setProperty("--depth", progress.toFixed(4));
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
      node.style.removeProperty("--depth");
    };
  }, [enabled, target]);

  return null;
}
