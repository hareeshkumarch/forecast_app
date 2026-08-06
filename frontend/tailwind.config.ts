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
      },
      animation: {
        "toast-in": "toast-in 160ms ease-out",
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
