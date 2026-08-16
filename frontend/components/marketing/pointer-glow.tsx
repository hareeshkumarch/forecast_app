"use client";

import { useEffect } from "react";

/**
 * Tracks the cursor inside every `.card-edge` on the page and writes its
 * position to `--glow-x` / `--glow-y` on the card under it. The CSS in
 * `globals.css` draws a soft highlight there; without these variables the
 * rule is inert, so the effect is additive and nothing depends on it.
 *
 * One delegated listener for the whole page, not one per card. Ten cards each
 * holding React state and re-rendering on pointermove would repaint the page
 * on every frame of a mouse movement, to move a gradient — the DOM write here
 * is a custom property on a single element, which only invalidates paint on
 * that card.
 *
 * Renders nothing. Mount it once inside the landing root.
 */
export function PointerGlow() {
  useEffect(() => {
    // A cursor is required, and so is a visitor who wants motion. On touch
    // there is no hover to track, and pointermove would fire on every scroll.
    const fine = window.matchMedia("(hover: hover) and (pointer: fine)");
    const still = window.matchMedia("(prefers-reduced-motion: reduce)");
    if (!fine.matches || still.matches) return;

    let frame = 0;
    let pending: { card: HTMLElement; x: number; y: number } | null = null;

    // Coalesced to one write per frame: pointermove can fire several times
    // between paints, and only the last position of those is visible.
    const flush = () => {
      frame = 0;
      if (!pending) return;
      const { card, x, y } = pending;
      pending = null;
      card.style.setProperty("--glow-x", `${x}px`);
      card.style.setProperty("--glow-y", `${y}px`);
    };

    const onMove = (event: PointerEvent) => {
      const card = (event.target as Element | null)?.closest?.<HTMLElement>(".card-edge");
      if (!card) return;
      const box = card.getBoundingClientRect();
      pending = { card, x: event.clientX - box.left, y: event.clientY - box.top };
      if (!frame) frame = requestAnimationFrame(flush);
    };

    // Park the highlight in the middle on the way out, so the fade-out shrinks
    // toward the centre instead of snapping to wherever the cursor left.
    const onLeave = (event: PointerEvent) => {
      const card = (event.target as Element | null)?.closest?.<HTMLElement>(".card-edge");
      if (!card) return;
      card.style.setProperty("--glow-x", "50%");
      card.style.setProperty("--glow-y", "50%");
    };

    document.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("pointerleave", onLeave, { capture: true, passive: true });
    return () => {
      if (frame) cancelAnimationFrame(frame);
      document.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerleave", onLeave, { capture: true });
    };
  }, []);

  return null;
}
