"use client";

import Link from "next/link";
import { useEffect, useRef, type ReactNode, type RefObject } from "react";

import { Arrow } from "@/components/marketing/floating-nav";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";
const FINE_POINTER = "(hover: hover) and (pointer: fine)";

/* Whole pixels, so a pointer resting on the button's own centre leaves the
   transform at exactly the 1px lift the stylesheet gives it. */
const PULL = 5;

function useMagnet(target: RefObject<HTMLElement>): void {
  useEffect(() => {
    const node = target.current;
    if (!node) return;
    if (window.matchMedia(REDUCED_MOTION).matches) return;
    if (!window.matchMedia(FINE_POINTER).matches) return;

    let frame = 0;
    const onMove = (event: PointerEvent) => {
      if (frame) return;
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        const box = node.getBoundingClientRect();
        const x = (event.clientX - box.left) / box.width - 0.5;
        const y = (event.clientY - box.top) / box.height - 0.5;
        node.style.setProperty("--magnet-x", `${Math.round(x * 2 * PULL)}px`);
        node.style.setProperty("--magnet-y", `${Math.round(y * 2 * PULL)}px`);
      });
    };

    const onLeave = () => {
      node.style.setProperty("--magnet-x", "0px");
      node.style.setProperty("--magnet-y", "0px");
    };

    node.addEventListener("pointermove", onMove);
    node.addEventListener("pointerleave", onLeave);
    return () => {
      if (frame) window.cancelAnimationFrame(frame);
      node.removeEventListener("pointermove", onMove);
      node.removeEventListener("pointerleave", onLeave);
    };
  }, [target]);
}

export function PrimaryCta({ href, children }: { href: string; children: ReactNode }) {
  const ref = useRef<HTMLAnchorElement>(null);
  useMagnet(ref);

  return (
    <Link
      ref={ref}
      href={href}
      className="cta-nudge group inline-flex h-[52px] items-center justify-center gap-3 border-2 border-land-cta bg-land-cta px-7 text-site-body font-medium text-land-cta-ink hover:border-accent hover:bg-land-cta-hover sm:h-[56px] sm:px-8"
    >
      {children}
      <Arrow />
    </Link>
  );
}

export function SecondaryCta({
  href,
  label,
  children,
}: {
  href: string;
  label?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLAnchorElement>(null);
  useMagnet(ref);

  return (
    <Link
      ref={ref}
      href={href}
      aria-label={label}
      className="hero-secondary-link inline-flex h-[52px] items-center justify-center border border-border-strong bg-surface/75 px-6 text-site-body font-medium text-text-secondary backdrop-blur-sm hover:border-text-muted hover:bg-surface sm:h-[56px]"
    >
      {children}
    </Link>
  );
}
