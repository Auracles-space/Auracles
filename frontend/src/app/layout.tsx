/**
 * Root layout for the Auracles Next.js app.
 *
 * Provides the global HTML shell, metadata, and font/CSS imports.
 * Every page nested under `app/` inherits this layout.
 */
import type { Metadata } from "next";
import localFont from "next/font/local";

import "./globals.css";

// Self-hosted rather than fetched from Google at build time.
//
// `next/font/google` downloads each face while compiling, which made every
// build depend on fonts.googleapis.com answering. It failed three builds out
// of four on 2026-10-14 with `next/font: Cannot read properties of null
// (reading '1')` — the loader regex-parsing a CSS response it never received.
// The same code runs in the Amplify production build, so a Google hiccup could
// fail a release, not just a PR.
//
// These are the latin subset only, at exactly the weights the brand book pins
// (Inter 600/700/800 for headings, Poppins 400/500/600 for body) — 74 KB in
// total. Both families are SIL Open Font License, which permits redistribution.
//
// Inter is one variable file carrying the whole weight axis, declared over the
// range the brand book uses. Google returns the same bytes for 600, 700 and
// 800, so listing it three times would ship the file three times. Poppins is
// static, hence one file per weight; adding a Poppins weight means adding its
// file here rather than editing a string.
const headingFont = localFont({
  display: "swap",
  src: [
    {
      path: "./fonts/inter-variable.woff2",
      style: "normal",
      weight: "600 800",
    },
  ],
  variable: "--font-heading",
});

const bodyFont = localFont({
  display: "swap",
  src: [
    { path: "./fonts/poppins-400.woff2", style: "normal", weight: "400" },
    { path: "./fonts/poppins-500.woff2", style: "normal", weight: "500" },
    { path: "./fonts/poppins-600.woff2", style: "normal", weight: "600" },
  ],
  variable: "--font-body",
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
import { StepUpDialog } from "@/components/step-up-dialog";
import { ThemeProvider } from "@/components/theme-provider";
import { ToastProvider } from "@/components/ui/toast";

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
          <ToastProvider>
            <IncompleteUserListener />
            <SessionTerminatedListener />
            <StepUpDialog />
            {children}
          </ToastProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
