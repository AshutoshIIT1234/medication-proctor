import type { NextConfig } from "next";

const backend = process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/backend/:path*',
        destination: `${backend}/sessions/:path*`,
      },
    ]
  },
};

export default nextConfig;
