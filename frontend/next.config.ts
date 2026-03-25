import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Allow the frontend to call the FastAPI backend during local dev
  async rewrites() {
    return [
      {
        source: "/api/backend/:path*",
        destination: `${process.env.BACKEND_URL ?? "http://localhost:8000"}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
