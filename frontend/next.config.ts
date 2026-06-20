import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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

