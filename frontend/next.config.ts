import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
        ],
      },
    ];
  },
  // Turbopack config (stable in Next.js 15+, top-level key).
  // Redirect onnxruntime-web to its pre-built UMD bundle so Turbopack
  // doesn't create broken dynamic .mjs WASM-backend chunks in production.
  turbopack: {
    resolveAlias: {
      "onnxruntime-web": "onnxruntime-web/dist/ort.min.js",
    },
  },
};

export default nextConfig;
