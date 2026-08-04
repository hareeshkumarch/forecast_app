import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import type { ReactNode } from "react";

import "./globals.css";
import { Providers } from "./providers";


const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: "Forecast Hub",
  description: "Forecast operations, reports, data connectors, and LLM usage analytics.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfaf7" },
    { media: "(prefers-color-scheme: dark)", color: "#14161b" },
  ],
};

/*
 * Runs before first paint so a dark-theme reload never flashes the light
 * palette. It mirrors readPrefs()/applyPrefs() in stores/prefs-store.ts.
 */
const THEME_BOOTSTRAP = `
(function () {
  try {
    var raw = localStorage.getItem("forecast_hub_prefs");
    var prefs = raw ? JSON.parse(raw) : {};
    var choice = prefs.theme === "light" || prefs.theme === "dark" ? prefs.theme : "system";
    var resolved = choice === "system"
      ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light")
      : choice;
    document.documentElement.dataset.theme = resolved;
    document.documentElement.dataset.density = prefs.density === "compact" ? "compact" : "comfortable";
  } catch (error) {
    document.documentElement.dataset.theme = "light";
    document.documentElement.dataset.density = "comfortable";
  }
})();
`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
