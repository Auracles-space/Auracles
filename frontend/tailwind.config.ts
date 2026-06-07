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
        // Surfaces — driven by CSS variables so they swap with mode
        background: "var(--background)",
        "surface-1": "var(--surface-1)",
        "surface-2": "var(--surface-2)",
        "surface-3": "var(--surface-3)",

        // Text
        foreground: "var(--foreground)",
        "foreground-muted": "var(--foreground-muted)",
        "foreground-subtle": "var(--foreground-subtle)",

        // Borders
        "border-default": "var(--border-default)",
        "border-strong": "var(--border-strong)",

        // Brand
        brand: {
          DEFAULT: "#0025CC",
          hover: "#0020B0",
          active: "#001A95",
        },

        // Semantic
        success: "#16A34A",
        warning: "#F59E0B",
        error: "#DC2626",
        info: "#2563EB",
      },
      fontFamily: {
        heading: ["var(--font-heading)", "Inter Rounded", "Inter", "sans-serif"],
        body: ["var(--font-body)", "Poppins", "sans-serif"],
      },
      borderRadius: {
        card: "8px",
        control: "6px",
        badge: "4px",
      },
    },
  },
  plugins: [],
};

export default config;
