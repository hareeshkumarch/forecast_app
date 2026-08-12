import type { Config } from "tailwindcss";
import plugin from "tailwindcss/plugin";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./hooks/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "var(--canvas)",
        surface: "var(--surface)",
        "surface-muted": "var(--surface-muted)",
        border: "var(--border)",
        "border-strong": "var(--border-strong)",

        "text-primary": "var(--text-primary)",
        "text-secondary": "var(--text-secondary)",
        "text-muted": "var(--text-muted)",

        accent: "var(--accent)",
        "accent-soft": "var(--accent-soft)",
        "accent-hover": "var(--accent-hover)",
        "accent-border": "var(--accent-border)",
        "accent-disabled": "var(--accent-disabled)",
        // Use text-on-accent, never text-white, on an accent fill.
        "on-accent": "var(--on-accent)",

        navy: "var(--navy)",
        teal: "var(--teal)",
        gold: "var(--gold)",
        sand: "var(--sand)",

        positive: "var(--positive)",
        "positive-soft": "var(--positive-soft)",
        "positive-border": "var(--positive-border)",
        negative: "var(--negative)",
        "negative-soft": "var(--negative-soft)",
        "negative-border": "var(--negative-border)",
        warning: "var(--warning)",
        "warning-soft": "var(--warning-soft)",
        "warning-border": "var(--warning-border)",
        overlay: "var(--overlay)",
      },
      borderRadius: {
        
        card: "2px",
        panel: "2px",
        input: "2px",
        chip: "1px",
      },
      spacing: {
        // Driven by the CSS variables in globals.css so these track the
        // viewport instead of being frozen at their desktop size — `h-header`
        // is 56px on a phone and 74px from `lg` up.
        rail: "var(--rail-width)",
        insights: "var(--insights-width)",
        header: "var(--header-height)",
      },
      fontFamily: {
        // Landing-page faces. The app keeps the `body` default (Inter) set in
        // globals.css; these are opted into, never inherited.
        display: ["var(--font-display)", "Georgia", "ui-serif", "serif"],
        plex: ["var(--font-plex-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-plex-mono)", "ui-monospace", "SFMono-Regular", "monospace"],
      },
      fontSize: {
        micro: ["11px", { lineHeight: "15px", letterSpacing: "0.05em" }],
        tag: ["9px", { lineHeight: "13px" }],
        caption: ["11.5px", { lineHeight: "16px" }],
        meta: ["12px", { lineHeight: "16px" }],
        "meta-tight": ["12px", { lineHeight: "1" }],
        body: ["13px", { lineHeight: "18px" }],
        subhead: ["14px", { lineHeight: "20px" }],
        title: ["16px", { lineHeight: "22px" }],
        heading: ["20px", { lineHeight: "26px" }],
        kpi: ["24px", { lineHeight: "30px" }],
        stat: ["clamp(1.75rem, 5.3vw, 2.125rem)", { lineHeight: "1.1", letterSpacing: "-0.03em" }],
        lead: ["17px", { lineHeight: "1.62" }],
        "site-display": [
          "clamp(2.625rem, calc(1.85rem + 3.4vw), 4.5rem)",
          { lineHeight: "1.04", letterSpacing: "-0.032em" },
        ],
        "site-h2": [
          "clamp(1.875rem, calc(1.45rem + 1.9vw), 2.75rem)",
          { lineHeight: "1.12", letterSpacing: "-0.025em" },
        ],
        "site-h3": ["clamp(1.125rem, calc(1rem + 0.4vw), 1.3125rem)", { lineHeight: "1.3", letterSpacing: "-0.02em" }],
        "site-lead": [
          "clamp(1.0625rem, calc(0.98rem + 0.36vw), 1.1875rem)",
          { lineHeight: "1.55" },
        ],
        "site-body": ["clamp(0.9375rem, calc(0.9rem + 0.2vw), 1.0625rem)", { lineHeight: "1.6" }],
        "site-caption": ["0.75rem", { lineHeight: "1.45", letterSpacing: "0.07em" }],
        "display-xs": ["27px", { lineHeight: "1.16", letterSpacing: "-0.015em" }],
        "display-sm": ["33px", { lineHeight: "1.14", letterSpacing: "-0.015em" }],
        "display-md": ["40px", { lineHeight: "1.12", letterSpacing: "-0.018em" }],
        "display-lg": ["52px", { lineHeight: "1.08", letterSpacing: "-0.02em" }],
        "display-xl": ["72px", { lineHeight: "1.02", letterSpacing: "-0.022em" }],
      },
      boxShadow: {
        card: "var(--shadow-card)",
        popover: "var(--shadow-popover)",
      },
      transitionDuration: {
        fast: "120ms",
      },
      keyframes: {
        "toast-in": {
          from: { opacity: "0", transform: "translateY(8px) scale(0.98)" },
          to: { opacity: "1", transform: "translateY(0) scale(1)" },
        },
        // The landing page's scroll choreography keeps its @keyframes in
        // globals.css next to the rules that reference them — Tailwind only
        // emits a keyframes block when a matching `animate-*` utility is
        // actually used in the markup, and those are driven from CSS.
        "pulse-dot": {
          "0%, 100%": { opacity: "1", transform: "scale(1)" },
          "50%": { opacity: "0.45", transform: "scale(0.82)" },
        },
        drift: {
          "0%, 100%": { transform: "translate3d(0, 0, 0) scale(1)" },
          "50%": { transform: "translate3d(2%, -3%, 0) scale(1.08)" },
        },
      },
      animation: {
        "toast-in": "toast-in 160ms ease-out",
        "pulse-dot": "pulse-dot 2.4s ease-in-out infinite",
        drift: "drift 22s ease-in-out infinite",
      },
    },
  },
  plugins: [
    /*
     * `fine:` — there is a mouse.
     *
     * Control heights used to shrink at `sm:`, which asks the wrong question.
     * Width is a proxy for input device and a bad one: a tablet held in two
     * hands is 768px wide and got a sixteen-pixel sort control, while a
     * desktop window dragged narrow got targets sized for a thumb nobody was
     * using. Asking about the pointer gets both right, at any width.
     */
    plugin(({ addVariant }) => {
      addVariant("fine", "@media (pointer: fine)");
    }),
  ],
};

export default config;
