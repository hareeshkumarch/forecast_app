import type { Metadata, Viewport } from "next";

import { SignIn } from "@/components/auth/sign-in";

export const metadata: Metadata = {
  title: "Sign in · Forecast Hub",
  description: "Sign in to your Forecast Hub planning workspace.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#f1f3ef",
};

export default function SignInPage() {
  return <SignIn />;
}
