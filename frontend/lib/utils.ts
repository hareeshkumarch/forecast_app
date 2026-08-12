import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

const FONT_SIZES = [
  "micro",
  "tag",
  "caption",
  "meta",
  "meta-tight",
  "body",
  "subhead",
  "title",
  "heading",
  "kpi",
  "stat",
  "lead",
  "site-display",
  "site-h2",
  "site-h3",
  "site-lead",
  "site-body",
  "site-caption",
  "display-xs",
  "display-sm",
  "display-md",
  "display-lg",
  "display-xl",
];

const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: FONT_SIZES }],
    },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
