import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      // Every color maps to its `-rgb` channel token via `<alpha-value>`.
      // A bare `var(--x)` cannot be parsed into an alpha color by Tailwind 3,
      // so modifiers like `bg-accent/10` would compile to nothing at all.
      // See the token block in `src/app/globals.css`.
      colors: {
        background: "rgb(var(--background-rgb) / <alpha-value>)",
        "surface-1": "rgb(var(--surface-1-rgb) / <alpha-value>)",
        "surface-2": "rgb(var(--surface-2-rgb) / <alpha-value>)",
        "surface-3": "rgb(var(--surface-3-rgb) / <alpha-value>)",

        foreground: "rgb(var(--foreground-rgb) / <alpha-value>)",
        "foreground-muted": "rgb(var(--foreground-muted-rgb) / <alpha-value>)",
        "foreground-subtle": "rgb(var(--foreground-subtle-rgb) / <alpha-value>)",

        "border-default": "rgb(var(--border-default-rgb) / <alpha-value>)",
        "border-strong": "rgb(var(--border-strong-rgb) / <alpha-value>)",

        // Gradient stops (also exposed via .brand-gradient utility class)
        brand: {
          peach: "rgb(var(--brand-peach-rgb) / <alpha-value>)",
          coral: "rgb(var(--brand-coral-rgb) / <alpha-value>)",
          magenta: "rgb(var(--brand-magenta-rgb) / <alpha-value>)",
          violet: "rgb(var(--brand-violet-rgb) / <alpha-value>)",
          indigo: "rgb(var(--brand-indigo-rgb) / <alpha-value>)",
        },

        accent: "rgb(var(--accent-rgb) / <alpha-value>)",

        success: "rgb(var(--success-rgb) / <alpha-value>)",
        warning: "rgb(var(--warning-rgb) / <alpha-value>)",
        error: "rgb(var(--error-rgb) / <alpha-value>)",
        info: "rgb(var(--info-rgb) / <alpha-value>)",
      },
      fontFamily: {
        heading: ["var(--font-heading)", "Inter Rounded", "Inter", "sans-serif"],
        body: ["var(--font-body)", "Poppins", "sans-serif"],
      },
      borderRadius: {
        badge: "999px",
        control: "10px",
        card: "20px",
        hero: "32px",
      },
      boxShadow: {
        card: "0 1px 2px rgba(10, 10, 10, 0.04), 0 8px 24px rgba(10, 10, 10, 0.06)",
        hero: "0 12px 48px rgba(199, 70, 52, 0.15)",
        bento: "0 8px 30px rgba(0, 0, 0, 0.04), 0 1px 3px rgba(0, 0, 0, 0.02)",
      },
      keyframes: {
        // Confirmation entrance: settles from slightly low and soft-focused so the
        // success panel reads as arriving, not as a layout jump.
        "fade-in": {
          from: { opacity: "0", transform: "translateY(6px)", filter: "blur(4px)" },
          to: { opacity: "1", transform: "translateY(0)", filter: "blur(0)" },
        },
      },
      animation: {
        "fade-in": "fade-in 420ms cubic-bezier(0.16, 1, 0.3, 1) both",
      },
    },
  },
  plugins: [],
};

export default config;
