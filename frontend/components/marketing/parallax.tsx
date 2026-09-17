"use client";

import { useEffect } from "react";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

const LEAD = 640;

type Tracked = { node: HTMLElement; top: number; span: number };

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
