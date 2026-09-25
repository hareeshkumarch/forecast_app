"use client";

import { useEffect } from "react";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

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

    return () => {
      observer?.disconnect();
      if (velFrame) cancelAnimationFrame(velFrame);
      window.removeEventListener("scroll", onScroll);
      for (const name of ["--vel", "--vel-abs"]) {
        node.style.removeProperty(name);
      }
      delete node.dataset.ambient;
    };
  }, [scene, ambient]);

  return null;
}
