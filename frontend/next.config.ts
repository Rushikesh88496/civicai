import type { NextConfig } from "next";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      { source: "/media/:path*", destination: `${API}/media/:path*` },
    ];
  },
  // Allow this machine's LAN IP to request dev-only assets (HMR, dev fonts)
  // when the dev server is reached through http://10.135.111.74:3000.
  allowedDevOrigins: ["10.135.111.74"],
  // Explicit project root. Without it Next.js scans lockfiles upward from the
  // project and warns about a stray package-lock.json in the user's home
  // directory (outside this Git repository); the auto-detected root already
  // equals this directory, so the value is behavior-neutral.
  turbopack: {
    root: __dirname,
  },
  experimental: {
    // This development machine has limited RAM (~7.5 GB), so Next's default
    // worker pool (one per CPU core) can exhaust memory during the page-data
    // collection phase of `next build`. Cap the build worker count.
    cpus: 2,
  },
};

export default nextConfig;
