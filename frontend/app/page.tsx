import type { Viewport } from "next";

import { Landing } from "@/components/marketing/landing";

/*
 * Both canvases, matched to the theme the browser is about to draw. A single
 * colour here painted a phone's status bar in drafting-paper grey above a
 * page that had gone dark, which is the seam a themed page is judged on.
 */
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f1f3ef" },
    { media: "(prefers-color-scheme: dark)", color: "#111512" },
  ],
};

export default function Page() {
  return <Landing />;
}
