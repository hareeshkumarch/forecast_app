"use client";

import type { ComponentPropsWithoutRef, CSSProperties, ElementType, ReactNode } from "react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";

const REDUCED_MOTION = "(prefers-reduced-motion: reduce)";

export function useMotionReady(): boolean {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const media = window.matchMedia(REDUCED_MOTION);
    let frame = 0;
    const update = () => {
      cancelAnimationFrame(frame);
      if (media.matches) setReady(false);
      else frame = requestAnimationFrame(() => setReady(true));
    };
    update();
    media.addEventListener("change", update);
    return () => {
      cancelAnimationFrame(frame);
      media.removeEventListener("change", update);
    };
  }, []);

  return ready;
}

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
  const revealDelay = Math.max(0, Math.min(delay, 900));
  const revealDuration = Math.max(180, Math.min(duration, 900));

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (window.matchMedia(REDUCED_MOTION).matches) {
      setShown(true);
      return;
    }

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
