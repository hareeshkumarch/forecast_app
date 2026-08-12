import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/*
 * tailwind-merge has to be told which `text-*` names are sizes. It classifies
 * anything it does not recognise as a colour, so `cn("text-site-lead",
 * "text-[#3f463f]")` dropped the size and kept only the colour — the element
 * fell back to the inherited body size while its class list still read as
 * though the token had been applied.
 */
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
