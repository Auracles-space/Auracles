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
      colors: {
        background: "var(--background)",
        "surface-1": "var(--surface-1)",
        "surface-2": "var(--surface-2)",
        "surface-3": "var(--surface-3)",

        foreground: "var(--foreground)",
        "foreground-muted": "var(--foreground-muted)",
        "foreground-subtle": "var(--foreground-subtle)",

        "border-default": "var(--border-default)",
        "border-strong": "var(--border-strong)",

        // Gradient stops (also exposed via .brand-gradient utility class)
        brand: {
          peach: "var(--brand-peach)",
          coral: "var(--brand-coral)",
          magenta: "var(--brand-magenta)",
          violet: "var(--brand-violet)",
          indigo: "var(--brand-indigo)",
        },

        accent: "var(--accent)",

        success: "#16a34a",
        warning: "#f59e0b",
        error: "#dc2626",
        info: "#2563eb",
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
    },
  },
  plugins: [],
};

export default config;
