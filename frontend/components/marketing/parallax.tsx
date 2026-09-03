"use client";

import { useEffect } from "react";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

/*
 * A stand-in for the viewport height, and the whole reason this is not a
 * `view()` timeline.
 *
 * A scroll-driven CSS animation measures an element against the scrollport,
 * and a full-page screenshot resizes the scrollport to the height of the
 * document — so the DOM reports one position and the capture paints another,
 * which is exactly the mismatch `audits/a1.mjs` reads as merged lines of
 * text. Progress here is a function of `scrollY` alone. Two readings at the
 * same scroll position agree, whatever the window is doing.
 */
const LEAD = 640;

type Tracked = { node: HTMLElement; top: number; span: number };

/**
 * Publishes each marked element's own scroll progress as `--sd`, 0 to 1.
 *
 * Written to the marked elements rather than to their sections: a custom
 * property invalidates style for everything below it, and a section is a
 * great deal of everything. How far each one travels is `--drift`, decided in
 * the markup, so adding a layer is an attribute rather than a subscription.
 */
export function ParallaxField({ selector }: { selector: string }) {
  useEffect(() => {
    if (window.matchMedia(REDUCED_MOTION).matches) return;

    const nodes = [...document.querySelectorAll<HTMLElement>(selector)];
    if (!nodes.length) return;

    let tracked: Tracked[] = [];
    let frame = 0;

    const measure = () => {
      tracked = nodes.map((node) => {
        const box = node.getBoundingClientRect();
        return {
          node,
          top: box.top + window.scrollY,
          span: Math.max(box.height + LEAD, 1),
        };
      });
    };

    const write = () => {
      frame = 0;
      const y = window.scrollY;
      for (const { node, top, span } of tracked) {
        const progress = Math.min(Math.max((y - top + LEAD) / span, 0), 1);
        node.style.setProperty("--sd", progress.toFixed(4));
      }
    };

    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(write);
    };

    const onResize = () => {
      measure();
      onScroll();
    };

    measure();
    write();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onResize, { passive: true });
    return () => {
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onResize);
      for (const { node } of tracked) node.style.removeProperty("--sd");
    };
  }, [selector]);

  return null;
}
