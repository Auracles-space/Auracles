import type { NextConfig } from "next";

// Proxy browser API traffic through the frontend origin so auth cookies
// (notably the middleware-read `session_hint`) are first-party. The browser
// calls `/api/*` on the Vercel domain; this rewrite forwards to the backend.
// `BACKEND_ORIGIN` overrides the destination per environment.
const BACKEND_ORIGIN =
  process.env.BACKEND_ORIGIN ?? "https://auracles-api.onrender.com";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND_ORIGIN}/:path*`,
      },
    ];
  },
  async redirects() {
    return [
      {
        source: "/dashboard/earnings",
        destination: "/dashboard/financials",
        permanent: true,
      },
      {
        source: "/dashboard/payouts",
        destination: "/dashboard/financials",
        permanent: true,
      },
    ];
  },
};

export default nextConfig;

