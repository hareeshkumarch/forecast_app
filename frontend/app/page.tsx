import type { Viewport } from "next";

import { Landing } from "@/components/marketing/landing";

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
