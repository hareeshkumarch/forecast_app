"use client";

import { useEffect } from "react";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";
const FINE_POINTER = "(hover: hover) and (pointer: fine)";

export type CinematicFieldProps = {
  /** The element the pointer and ambient state are written to. */
  scene: string;
  /** The section whose visibility decides whether ambient motion runs. */
  ambient: string;
};

/**
 * One listener each for the pointer and for the hero's visibility, both
 * writing to a single element.
 *
 * `--px` / `--py` are document pixels, so a layer inside the hero can be
 * placed at the cursor with a transform and nothing has to be measured on
 * the way. `data-ambient` is what stops the drifting light costing anything
 * once the hero has left: every ambient keyframe below is paused by it.
 */
export function CinematicField({ scene, ambient }: CinematicFieldProps) {
  useEffect(() => {
    const node = document.querySelector<HTMLElement>(scene);
    if (!node) return;
    if (window.matchMedia(REDUCED_MOTION).matches) return;

    node.dataset.ambient = "on";

    const stage = document.querySelector<HTMLElement>(ambient);
    const observer = stage
      ? new IntersectionObserver(
          ([entry]) => {
            node.dataset.ambient = entry?.isIntersecting ? "on" : "off";
          },
          { threshold: 0 },
        )
      : null;
    if (stage && observer) observer.observe(stage);

    const fine = window.matchMedia(FINE_POINTER).matches;
    let frame = 0;
    let x = 0;
    let y = 0;

    const write = () => {
      frame = 0;
      node.style.setProperty("--px", `${Math.round(x)}px`);
      node.style.setProperty("--py", `${Math.round(y)}px`);
    };

    const onMove = (event: PointerEvent) => {
      x = event.clientX;
      y = event.clientY + window.scrollY;
      if (node.dataset.pointer !== "on") node.dataset.pointer = "on";
      if (frame) return;
      frame = requestAnimationFrame(write);
    };

    const onOut = (event: PointerEvent) => {
      if (event.relatedTarget) return;
      node.dataset.pointer = "off";
    };

    if (fine) {
      window.addEventListener("pointermove", onMove, { passive: true });
      document.addEventListener("pointerout", onOut);
    }

    return () => {
      observer?.disconnect();
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerout", onOut);
      node.style.removeProperty("--px");
      node.style.removeProperty("--py");
      delete node.dataset.ambient;
      delete node.dataset.pointer;
    };
  }, [scene, ambient]);

  return null;
}
