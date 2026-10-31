import type { NextConfig } from "next";

const config: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/backend/:path*",
        destination:
          (process.env.API_ORIGIN || "http://127.0.0.1:8100") + "/:path*",
      },
    ];
  },
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/app/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
        ],
      },
      ...[
        "/signin",
        "/verify-email",
        "/reset-password",
        "/forgot-password",
      ].map((source) => ({
        source,
        headers: [{ key: "X-Frame-Options", value: "DENY" }],
      })),
    ];
  },
};
export default config;
