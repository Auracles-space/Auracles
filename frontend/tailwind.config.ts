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
        hover: "#262626",
        active: "#303030",
        selected: "#525252",
        primary: "#F5F5F5",
        secondary: "#A3A3A3",
        muted: "#737373",
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
