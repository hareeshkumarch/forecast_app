"use client";

import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { activeStep, beats } from "@/lib/pipeline";
import { cn } from "@/lib/utils";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

/* A pinned panel taller than the window cannot stick, and a section three
   screens tall that never animates is three screens of nothing. Below this the
   section stays an ordinary block with the drawing already finished. */
const MIN_HEIGHT = 600;

export type ScrollStageProps = {
  /** How many screens of scroll the build is given. */
  screens?: number;
  className?: string;
  children: ReactNode;
};

/**
 * Pins its child and turns the scroll past it into a 0–1 progress.
 *
 * Everything downstream reads that progress as four custom properties, so a
 * frame costs one element's style write and no React render at all — the
 * alternative, holding the progress in state, re-renders four hundred SVG
 * nodes on every scroll event to move a few of them.
 *
 * Pinning is opt-in from the client, like the rest of this page's motion: the
 * server sends, and a visitor who asked for stillness keeps, a section of
 * ordinary height with the build already at its finished state.
 */
export function ScrollStage({ screens = 3, className, children }: ScrollStageProps) {
  // The track's height in pixels, or zero for "do not pin this".
  const [track, setTrack] = useState(0);
  const trackRef = useRef<HTMLDivElement>(null);
  const pinRef = useRef<HTMLDivElement>(null);
  const frame = useRef(0);
  const step = useRef(-1);
  const live = track > 0;

  /*
   * Measured in pixels once, rather than left as `300vh`.
   *
   * The obvious way to ask for three screens of scroll is to say so in CSS,
   * and it makes the section's height a live function of the window's. A
   * phone's address bar collapsing is a viewport-height change: mid-scrub the
   * track would grow by a fifth, the progress underneath the reader's thumb
   * would jump backwards, and the build would run in reverse for a frame.
   * Anything else that resizes the viewport height — devtools, a full-page
   * screenshot — moves it the same way.
   *
   * The width is what the layout actually depends on, so that is what a
   * remeasure is keyed to.
   */
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

  /*
   * A deep link lands where it was aimed.
   *
   * The browser scrolls to `#compare` before React has hydrated, and the track
   * then grows by three screens underneath it — so `/#compare` arrived two
   * thousand pixels above the section it named, and so did every anchor below
   * this one. `audits/track-a.mjs` measures exactly that, on a cold hash.
   *
   * Once, on the first frame the track has a height, and only when the anchor
   * is not already on screen: after that the height is settled and a nav click
   * needs no help.
   */
  const corrected = useRef(false);
  useEffect(() => {
    if (!live || corrected.current) return;
    corrected.current = true;

    const node = trackRef.current;
    const target = document.getElementById(window.location.hash.slice(1));
    if (!node || !target) return;

    // Anchors above the track never moved.
    const below = node.compareDocumentPosition(target) & Node.DOCUMENT_POSITION_FOLLOWING;
    if (!below) return;

    // And nothing to correct if the anchor is already where it was aimed —
    // which is the usual case, because a router that does its own hash scroll
    // after hydration has already read the settled height. Checking rather
    // than always scrolling is what keeps this from yanking back a visitor
    // who started scrolling before it ran.
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
      // The pin's own `top` is where it comes to rest, so it is also the point
      // the track has to have reached for the build to be at zero. Read from
      // the stylesheet rather than duplicated here — the header it clears is
      // a different height at every breakpoint.
      const rest = parseFloat(getComputedStyle(pin).top) || 0;
      const travel = node.offsetHeight - pin.offsetHeight;
      if (travel <= 0) return;

      const top = node.getBoundingClientRect().top - rest;
      const progress = Math.min(Math.max(-top / travel, 0), 1);
      const { fill, read, build, ahead } = beats(progress);

      node.style.setProperty("--t-fill", fill.toFixed(4));
      node.style.setProperty("--t-read", read.toFixed(4));
      node.style.setProperty("--t-build", build.toFixed(4));
      node.style.setProperty("--t-ahead", ahead.toFixed(4));

      // An attribute write invalidates style for the subtree, so it happens
      // only when the answer has actually changed rather than every frame.
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
      for (const name of ["--t-fill", "--t-read", "--t-build", "--t-ahead"]) {
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
      data-step={live ? 0 : undefined}
    >
      <div ref={pinRef} className="scroll-pin">
        {children}
      </div>
    </div>
  );
}
