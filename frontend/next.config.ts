import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // Cache Components are not used: every page shows live, per-analysis data rendered on request.
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
