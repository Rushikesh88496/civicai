import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  experimental: {
    // This development machine has limited RAM (~7.5 GB), so Next's default
    // worker pool (one per CPU core) can exhaust memory during the page-data
    // collection phase of `next build`. Cap the build worker count.
    cpus: 2,
  },
};

export default nextConfig;
