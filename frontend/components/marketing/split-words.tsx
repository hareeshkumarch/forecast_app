"use client";

import { Fragment } from "react";
import type { ComponentPropsWithoutRef, CSSProperties, ElementType } from "react";

import { Reveal } from "@/components/marketing/reveal";
import { cn } from "@/lib/utils";

/**
 * A heading that arrives a word at a time.
 *
 * The words are real text nodes with real spaces between them, so the line
 * breaks, the accessible name and `text-wrap: balance` are all exactly what
 * they would be without this — only the paint is staggered. The container
 * itself does not fade (`variant="words"`), because a fading parent and
 * fading children multiply into a heading that never quite reaches full
 * opacity.
 *
 * Like everything else on this page the motion is scoped to `.motion-ready`,
 * so a visitor who asked for reduced motion, or arrives with no JavaScript,
 * gets the finished heading.
 */
export type SplitWordsProps = {
  text: string;
  as?: ElementType;
  /** Milliseconds before the first word moves. */
  delay?: number;
  /** Milliseconds between one word and the next. */
  stagger?: number;
} & Omit<ComponentPropsWithoutRef<"div">, "children">;

//: Long headings would otherwise finish well after the reader has read them.
const MAX_STAGGER_TOTAL = 620;

export function SplitWords({
  text,
  as = "h2",
  delay = 0,
  stagger = 60,
  className,
  ...rest
}: SplitWordsProps) {
  const words = text.split(" ").filter(Boolean);
  const step = Math.min(stagger, MAX_STAGGER_TOTAL / Math.max(words.length, 1));

  return (
    <Reveal as={as} variant="words" delay={delay} className={cn("split-words", className)} {...rest}>
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
