import type { NextConfig } from "next";

// The FastAPI server. The browser calls /api/*, and Next.js forwards it there, so the
// API needs no CORS configuration and the UI never hard-codes its address.
const apiUrl = process.env.EKA_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }];
  },
};

export default nextConfig;
