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
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
