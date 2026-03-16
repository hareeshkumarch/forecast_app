import { Link, useLocation } from "wouter";
import {
  BarChart3, Upload, Clock, TrendingUp, Moon, Sun,
} from "lucide-react";
import { useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { MlHealthBanner } from "@/components/ml-health-banner";

const THEME_KEY = "forecast_hub_theme";

const NAV_ITEMS = [
  { href: "/", icon: Upload, label: "New Forecast" },
  { href: "/history", icon: Clock, label: "History" },
  { href: "/database", icon: BarChart3, label: "Database" },
];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const [location] = useLocation();
  const [dark, setDark] = useState(() => {
    if (typeof window === "undefined") return false;
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "dark" || stored === "light") return stored === "dark";
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try {
      localStorage.setItem(THEME_KEY, dark ? "dark" : "light");
    } catch { }
  }, [dark]);

  return (
    <div className="h-screen overflow-hidden relative flex">
      {/* Animated Mesh Gradient Background */}
      <div className="mesh-bg" aria-hidden="true"></div>

      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:px-3 focus:py-2 focus:bg-primary focus:text-primary-foreground focus:rounded-md focus:outline-none focus:ring-2 focus:ring-ring"
      >
        Skip to main content
      </a>
      {/* Sidebar with Glassmorphism */}
      <aside className="w-56 border-r border-border/40 bg-card/40 backdrop-blur-xl flex flex-col shrink-0 relative shadow-2xl z-20" aria-label="App sidebar">
        {/* Subtle Right Edge Glow */}
        <div className="absolute top-0 bottom-0 right-0 w-[1px] bg-gradient-to-b from-transparent via-primary/20 to-transparent"></div>

        <div className="px-5 py-5 border-b border-border/40">
          <Link href="/">
            <div className="flex items-center gap-3 cursor-pointer group" data-testid="link-home">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-primary to-chart-2 flex items-center justify-center shadow-lg shadow-primary/20 group-hover:scale-105 transition-transform" aria-hidden>
                <TrendingUp className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-[15px] font-bold text-foreground leading-tight tracking-tight">ForecastHub</h1>
                <p className="text-[11px] text-muted-foreground leading-tight font-medium">Analytics Engine</p>
              </div>
            </div>
          </Link>
        </div>

        <nav className="flex-1 px-3 py-4 space-y-1" aria-label="Main navigation">
          <ul className="space-y-1" role="list">
            {NAV_ITEMS.map((item) => {
              const isActive = location === item.href || (item.href !== "/" && location.startsWith(item.href));
              const Icon = item.icon;
              return (
                <li key={item.href} role="none">
                  <Link href={item.href}>
                    <div
                      className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm cursor-pointer transition-all relative ${isActive
                        ? "bg-primary/10 text-primary font-semibold shadow-sm overflow-hidden"
                        : "text-muted-foreground font-medium hover:text-foreground hover:bg-muted/50"
                        }`}
                      data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, "-")}`}
                      role="link"
                    >
                      {isActive && (
                        <div className="absolute left-0 top-1 bottom-1 w-1 bg-primary rounded-r-full shadow-[0_0_8px_rgba(var(--primary),0.8)]" />
                      )}
                      <Icon className={`w-[18px] h-[18px] ${isActive ? "text-primary drop-shadow-[0_0_5px_rgba(var(--primary),0.5)]" : ""}`} aria-hidden />
                      {item.label}
                    </div>
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="px-4 py-4 border-t border-border/40 space-y-2 relative">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start gap-2.5 text-[13px] font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 rounded-lg"
            onClick={() => setDark(!dark)}
            data-testid="btn-theme-toggle"
            aria-pressed={dark}
            aria-label={dark ? "Switch to light mode" : "Switch to dark mode"}
          >
            {dark ? <Sun className="w-4 h-4" aria-hidden /> : <Moon className="w-4 h-4" aria-hidden />}
            {dark ? "Light mode" : "Dark mode"}
          </Button>
        </div>
      </aside>

      <main id="main-content" className="flex-1 overflow-y-auto flex flex-col relative z-10" role="main">
        <MlHealthBanner />
        <div className="flex-1">{children}</div>
      </main>
    </div>
  );
}
