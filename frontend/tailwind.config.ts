import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "#0A0A0A",
        sidebar: "#111111",
        surface: "#161616",
        card: "#1A1A1A",
        border: "#2A2A2A",
        "border-hover": "#3A3A3A",
        hover: "#262626",
        active: "#303030",
        selected: "#525252",
        primary: "#F5F5F5",
        secondary: "#A3A3A3",
        muted: "#737373",
        status: {
          "success-bg": "#1A2A1A",
          "success-border": "#2A3A2A",
          "success-text": "#86EFAC",
          "warning-bg": "#2A2010",
          "warning-border": "#3A3020",
          "warning-text": "#FCD34D",
          "error-bg": "#2A1010",
          "error-border": "#3A2020",
          "error-text": "#FCA5A5",
          "info-bg": "#101A2A",
          "info-border": "#202A3A",
          "info-text": "#93C5FD",
        },
      },
      fontFamily: {
        heading: ["Inter Rounded", "Inter", "sans-serif"],
        body: ["Poppins", "sans-serif"],
      },
      borderRadius: {
        card: "8px",
        control: "6px",
      },
    },
  },
  plugins: [],
};

export default config;
