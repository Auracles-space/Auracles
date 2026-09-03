import type { NextConfig } from "next";

// Proxy browser API traffic through the frontend origin so auth cookies
// (notably the middleware-read `session_hint`) are first-party. The browser
// calls `/api/*` on the app's own domain; this rewrite forwards to the backend.
// `BACKEND_ORIGIN` sets the destination per environment and is read at BUILD
// time — changing it in the Amplify console requires a rebuild, not a restart.
//
// The fallback is localhost deliberately. It used to be the Render origin the
// platform has since left, which failed in the worst possible way: a deploy
// that forgot the variable still *worked* until Render stopped answering, and
// a hostname we no longer own is a hostname someone else can register and then
// receive our proxied API traffic on. Localhost cannot be hijacked, and a
// deployed build that reaches for it fails immediately and obviously.
const BACKEND_ORIGIN = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

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
        // The contributor profile was unified into the canonical, all-roles
        // profile at /profile/:id.
        source: "/explore/contributors/:id",
        destination: "/profile/:id",
        permanent: true,
      },
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

