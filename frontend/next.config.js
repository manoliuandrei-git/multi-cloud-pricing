/** @type {import('next').NextConfig} */
const nextConfig = {
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

module.exports = nextConfig;
