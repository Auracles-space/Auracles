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
  title: "Institutional Intelligence Infrastructure",
  description: "Marketplace infrastructure for trusted frameworks.",
  icons: {
    icon: [
      {
        url: "/images/favicon-black.png",
        media: "(prefers-color-scheme: light)",
      },
      {
        url: "/images/favicon-white.png",
        media: "(prefers-color-scheme: dark)",
      },
    ],
  },
};

import { IncompleteUserListener } from "@/components/incomplete-user-listener";
import { SessionTerminatedListener } from "@/components/session-terminated-listener";
import { ThemeProvider } from "@/components/theme-provider";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${headingFont.variable} ${bodyFont.variable}`}>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <IncompleteUserListener />
          <SessionTerminatedListener />
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
