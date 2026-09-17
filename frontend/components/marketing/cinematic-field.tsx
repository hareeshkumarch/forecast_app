"use client";

import { useEffect } from "react";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";
const FINE_POINTER = "(hover: hover) and (pointer: fine)";

export type CinematicFieldProps = {
  scene: string;
  ambient: string;
};

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

    let velFrame = 0;
    let last = window.scrollY;
    let vel = 0;

    const settle = () => {
      velFrame = 0;
      const now = window.scrollY;
      const step = Math.max(-1, Math.min((now - last) / (window.innerHeight * 0.5), 1));
      last = now;
      vel = vel * 0.82 + step * 0.5;
      if (Math.abs(vel) < 0.002) vel = 0;
      node.style.setProperty("--vel", vel.toFixed(4));
      node.style.setProperty("--vel-abs", Math.abs(vel).toFixed(4));
      if (vel !== 0) velFrame = requestAnimationFrame(settle);
    };

    const onScroll = () => {
      if (velFrame) return;
      velFrame = requestAnimationFrame(settle);
    };

    window.addEventListener("scroll", onScroll, { passive: true });

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
      if (velFrame) cancelAnimationFrame(velFrame);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerout", onOut);
      for (const name of ["--px", "--py", "--vel", "--vel-abs"]) {
        node.style.removeProperty(name);
      }
      delete node.dataset.ambient;
      delete node.dataset.pointer;
    };
  }, [scene, ambient]);

  return null;
}
