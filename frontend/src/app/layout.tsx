/**
 * Root layout for the Auracles Next.js app.
 *
 * Provides the global HTML shell, metadata, and font/CSS imports.
 * Every page nested under `app/` inherits this layout.
 */
import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Auracles",
  description: "Knowledge marketplace foundation status.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body>{children}</body>
    </html>
  );
}
