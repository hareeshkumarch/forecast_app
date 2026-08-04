import type { Config } from "tailwindcss";


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

        navy: "var(--navy)",
        teal: "var(--teal)",
        gold: "var(--gold)",
        sand: "var(--sand)",

        positive: "var(--positive)",
        "positive-soft": "var(--positive-soft)",
        negative: "var(--negative)",
        "negative-soft": "var(--negative-soft)",
        warning: "var(--warning)",
        "warning-soft": "var(--warning-soft)",
      },
      borderRadius: {
        
        card: "12px",
        panel: "12px",
        input: "9px",
        chip: "6px",
      },
      spacing: {
        
        rail: "224px",
        insights: "320px",
        header: "74px",
      },
      fontSize: {
        micro: ["10px", { lineHeight: "14px", letterSpacing: "0.06em" }],
        caption: ["11px", { lineHeight: "16px" }],
        meta: ["12px", { lineHeight: "16px" }],
        body: ["13px", { lineHeight: "18px" }],
        subhead: ["14px", { lineHeight: "20px" }],
        title: ["16px", { lineHeight: "22px" }],
        heading: ["20px", { lineHeight: "26px" }],
        kpi: ["24px", { lineHeight: "30px" }],
      },
      boxShadow: {
        
        card: "0 1px 2px rgba(24, 32, 47, 0.04)",
        popover: "0 8px 24px rgba(24, 32, 47, 0.10), 0 2px 6px rgba(24, 32, 47, 0.06)",
      },
      transitionDuration: {
        fast: "120ms",
      },
    },
  },
  plugins: [],
};

export default config;
