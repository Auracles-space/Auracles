/**
 * Root layout for the Auracles Next.js app.
 *
 * Provides the global HTML shell, metadata, and font/CSS imports.
 * Every page nested under `app/` inherits this layout.
 */
import type { Metadata } from "next";
import { Inter, Poppins } from "next/font/google";

import "./globals.css";

const headingFont = Inter({
  display: "swap",
  subsets: ["latin"],
  variable: "--font-heading",
  weight: ["600", "700", "800"],
});

const bodyFont = Poppins({
  display: "swap",
  subsets: ["latin"],
  variable: "--font-body",
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Auracles",
  description: "Knowledge marketplace foundation status.",
};

const themeBootstrap = `
  try {
    const storedTheme = window.localStorage.getItem("auracles-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const useDark = storedTheme ? storedTheme === "dark" : prefersDark;
    document.documentElement.classList.toggle("dark", useDark);
    document.documentElement.style.colorScheme = useDark ? "dark" : "light";
  } catch {
    document.documentElement.style.colorScheme = "light";
  }
`;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootstrap }} />
      </head>
      <body className={`${headingFont.variable} ${bodyFont.variable}`}>
        {children}
      </body>
    </html>
  );
}
