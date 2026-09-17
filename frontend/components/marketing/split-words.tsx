"use client";

import { Fragment } from "react";
import type { ComponentPropsWithoutRef, CSSProperties, ElementType } from "react";

import { Reveal } from "@/components/marketing/reveal";
import { cn } from "@/lib/utils";

export type SplitWordsProps = {
  text: string;
  as?: ElementType;
  delay?: number;
  stagger?: number;
  motion?: "rise" | "cinematic";
} & Omit<ComponentPropsWithoutRef<"div">, "children">;

const MAX_STAGGER_TOTAL = 620;

export function SplitWords({
  text,
  as = "h2",
  delay = 0,
  stagger = 60,
  motion = "rise",
  className,
  ...rest
}: SplitWordsProps) {
  const words = text.split(" ").filter(Boolean);
  const step = Math.min(stagger, MAX_STAGGER_TOTAL / Math.max(words.length, 1));

  return (
    <Reveal
      as={as}
      variant="words"
      delay={delay}
      data-motion={motion}
      className={cn("split-words", className)}
      {...rest}
    >
      {words.map((word, index) => (
        <Fragment key={`${word}-${index}`}>
          <span
            className="split-word"
            style={{ "--word-delay": `${Math.round(index * step)}ms` } as CSSProperties}
          >
            {word}
          </span>
          {index < words.length - 1 ? " " : null}
        </Fragment>
      ))}
    </Reveal>
  );
}
