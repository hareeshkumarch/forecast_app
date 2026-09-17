"use client";

import { useEffect, useRef, useState } from "react";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

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
