import type { Viewport } from "next";

import { Landing } from "@/components/marketing/landing";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#f1f3ef",
};

export default function Page() {
  return <Landing />;
}
