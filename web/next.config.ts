import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    agentUpgrade: "security",
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return {
      beforeFiles: [
        {
          source: "/",
          has: [
            {
              type: "header",
              key: "accept",
              value: "^text/markdown.*",
            },
          ],
          destination: "/llms-full.txt",
        },
        {
          source: "/:locale(az|ru)",
          has: [
            {
              type: "header",
              key: "accept",
              value: "^text/markdown.*",
            },
          ],
          destination: "/llms-full.txt",
        },
      ],
    };
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
          {
            key: "X-Frame-Options",
            value: "DENY",
          },
          {
            key: "X-Content-Type-Options",
            value: "nosniff",
          },
          {
            key: "Referrer-Policy",
            value: "strict-origin-when-cross-origin",
          },
          {
            key: "Content-Security-Policy",
            value: "frame-ancestors 'none'",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=()",
          },
        ],
      },
      {
        source: "/",
        has: [
          {
            type: "header",
            key: "accept",
            value: "^text/markdown.*",
          },
        ],
        headers: [
          {
            key: "Content-Type",
            value: "text/markdown; charset=utf-8",
          },
        ],
      },
      {
        source: "/:locale(az|ru)",
        has: [
          {
            type: "header",
            key: "accept",
            value: "^text/markdown.*",
          },
        ],
        headers: [
          {
            key: "Content-Type",
            value: "text/markdown; charset=utf-8",
          },
        ],
      },
      {
        source: "/llms.txt",
        headers: [
          {
            key: "Content-Type",
            value: "text/markdown; charset=utf-8",
          },
        ],
      },
      {
        source: "/llms-full.txt",
        headers: [
          {
            key: "Content-Type",
            value: "text/markdown; charset=utf-8",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
