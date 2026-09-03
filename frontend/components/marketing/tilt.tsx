"use client";

import { useEffect, type RefObject } from "react";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

/**
 * Leans a panel towards the pointer, as `--tilt-x` / `--tilt-y` on the node.
 *
 * Written to the element rather than held in state: this fires on every
 * pointer move, and a card that re-renders its whole subtree to turn by a
 * degree is the most expensive thing on the section.
 */
export function useTilt(target: RefObject<HTMLElement>, strength = 9): void {
  useEffect(() => {
    const node = target.current;
    if (!node) return;
    if (window.matchMedia(REDUCED_MOTION).matches) return;
    if (window.matchMedia("(hover: none)").matches) return;

    let frame = 0;
    const onMove = (event: PointerEvent) => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        const box = node.getBoundingClientRect();
        const x = (event.clientX - box.left) / box.width - 0.5;
        const y = (event.clientY - box.top) / box.height - 0.5;
        node.style.setProperty("--tilt-x", `${(-y * strength).toFixed(3)}deg`);
        node.style.setProperty("--tilt-y", `${(x * strength).toFixed(3)}deg`);
      });
    };

    const onLeave = () => {
      node.style.setProperty("--tilt-x", "0deg");
      node.style.setProperty("--tilt-y", "0deg");
    };

    node.addEventListener("pointermove", onMove);
    node.addEventListener("pointerleave", onLeave);
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      node.removeEventListener("pointermove", onMove);
      node.removeEventListener("pointerleave", onLeave);
    };
  }, [target, strength]);
}
