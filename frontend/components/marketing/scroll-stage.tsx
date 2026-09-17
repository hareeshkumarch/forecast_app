"use client";

import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { activeStep, beats } from "@/lib/pipeline";
import { cn } from "@/lib/utils";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

const MIN_HEIGHT = 600;

export type ScrollStageProps = {
  screens?: number;
  stage?: string;
  className?: string;
  children: ReactNode;
};

export function ScrollStage({ screens = 3, stage, className, children }: ScrollStageProps) {
  const [track, setTrack] = useState(0);
  const trackRef = useRef<HTMLDivElement>(null);
  const pinRef = useRef<HTMLDivElement>(null);
  const frame = useRef(0);
  const step = useRef(-1);
  const live = track > 0;

  useEffect(() => {
    let measured = -1;
    const decide = () => {
      if (window.matchMedia(REDUCED_MOTION).matches || window.innerHeight < MIN_HEIGHT) {
        measured = -1;
        setTrack(0);
        return;
      }
      if (window.innerWidth === measured) return;
      measured = window.innerWidth;
      setTrack(Math.round(screens * window.innerHeight));
    };

    decide();
    window.addEventListener("resize", decide);
    return () => window.removeEventListener("resize", decide);
  }, [screens]);

  const corrected = useRef(false);
  useEffect(() => {
    if (!live || corrected.current) return;
    corrected.current = true;

    const node = trackRef.current;
    const target = document.getElementById(window.location.hash.slice(1));
    if (!node || !target) return;

    const below = node.compareDocumentPosition(target) & Node.DOCUMENT_POSITION_FOLLOWING;
    if (!below) return;

    const box = target.getBoundingClientRect();
    if (box.top >= 0 && box.top < window.innerHeight / 2) return;

    target.scrollIntoView({ behavior: "instant", block: "start" });
  }, [live]);

  useEffect(() => {
    if (!live) return;
    const node = trackRef.current;
    const pin = pinRef.current;
    if (!node || !pin) return;

    const write = () => {
      frame.current = 0;
      const rest = parseFloat(getComputedStyle(pin).top) || 0;
      const travel = node.offsetHeight - pin.offsetHeight;
      if (travel <= 0) return;

      const top = node.getBoundingClientRect().top - rest;
      const progress = Math.min(Math.max(-top / travel, 0), 1);
      const { fill, read, build, ahead } = beats(progress);

      node.style.setProperty("--t", progress.toFixed(4));
      node.style.setProperty("--t-fill", fill.toFixed(4));
      node.style.setProperty("--t-read", read.toFixed(4));
      node.style.setProperty("--t-build", build.toFixed(4));
      node.style.setProperty("--t-ahead", ahead.toFixed(4));

      const current = activeStep(progress);
      if (current !== step.current) {
        step.current = current;
        node.dataset.step = String(current);
      }
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
      step.current = -1;
      for (const name of ["--t", "--t-fill", "--t-read", "--t-build", "--t-ahead"]) {
        node.style.removeProperty(name);
      }
      delete node.dataset.step;
    };
  }, [live]);

  return (
    <div
      ref={trackRef}
      className={cn("scroll-track", live && "scroll-track--live", className)}
      style={live ? { minHeight: `${track}px` } : undefined}
      data-stage={stage}
      data-step={live ? 0 : undefined}
    >
      <div ref={pinRef} className="scroll-pin">
        {children}
      </div>
    </div>
  );
}
