"use client";

import type { ComponentPropsWithoutRef, CSSProperties, ElementType, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

/**
 * Arms the scroll choreography for the subtree below it.
 *
 * The `.motion-ready` class is what makes `.reveal` start hidden, and it is
 * added here — after mount, and never when the visitor has asked for reduced
 * motion. Server output and no-JS output are therefore the finished page,
 * and the animation is a progressive enhancement rather than a prerequisite
 * for seeing anything.
 */
export function useMotionReady(): boolean {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (window.matchMedia(REDUCED_MOTION).matches) return;
    // A frame's delay so the hidden state is painted before the observer can
    // flip it back — otherwise the first section above the fold never moves.
    const frame = requestAnimationFrame(() => setReady(true));
    return () => cancelAnimationFrame(frame);
  }, []);

  return ready;
}

/**
 * Reveals its children once they scroll into view, once. `delay` staggers
 * siblings; `amount` is how much of the element has to be visible first.
 */
export type RevealProps = {
  as?: ElementType;
  delay?: number;
  amount?: number;
  variant?: "rise" | "scale" | "from-left" | "from-right" | "fade" | "words";
  duration?: number;
  children: ReactNode;
} & Omit<ComponentPropsWithoutRef<"div">, "children">;

export function Reveal({
  as: Tag = "div",
  delay = 0,
  amount = 0.2,
  variant = "rise",
  duration = 520,
  className,
  style,
  children,
  ...rest
}: RevealProps) {
  const ref = useRef<HTMLElement>(null);
  const [shown, setShown] = useState(false);
  // Clamped at 420 a three-item stagger collapsed: the second and third
  // arrived together, so a sequence read as a single pop. 900 is still short
  // enough that nobody waits for the last one.
  const revealDelay = Math.max(0, Math.min(delay, 900));
  const revealDuration = Math.max(180, Math.min(duration, 900));

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (window.matchMedia(REDUCED_MOTION).matches) {
      setShown(true);
      return;
    }

    // Anything taller than the viewport can never reach a 20% threshold from
    // the top, so clamp what we ask for against the element's own height.
    const ratio = Math.min(amount, (window.innerHeight * 0.6) / Math.max(node.offsetHeight, 1));

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        setShown(true);
        observer.disconnect();
      },
      { threshold: Math.max(0, Math.min(ratio, 1)), rootMargin: "0px 0px -8% 0px" },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [amount]);

  return (
    <Tag
      ref={ref}
      data-shown={shown ? "true" : undefined}
      data-reveal={variant}
      className={cn("reveal", className)}
      style={{
        ...style,
        "--reveal-delay": `${revealDelay}ms`,
        "--reveal-duration": `${revealDuration}ms`,
      } as CSSProperties}
      {...rest}
    >
      {children}
    </Tag>
  );
}
