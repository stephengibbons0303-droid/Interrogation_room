import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          // Keeps cross-origin popups from accessing this window.
          // COEP is intentionally omitted: we use numThreads=1 in onnxruntime-web
          // so SharedArrayBuffer is not needed, and COEP can break CDN/third-party assets.
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
        ],
      },
    ];
  },
  experimental: {
    turbo: {
      resolveAlias: {
        // Redirect onnxruntime-web to its pre-built UMD bundle.
        // The default modular entry uses dynamic import() for WASM backends,
        // which Turbopack splits into separate .mjs chunks that 404 in production.
        // ort.min.js is a single self-contained file with no dynamic imports;
        // WASM binaries are still loaded at runtime via ort.env.wasm.wasmPaths.
        "onnxruntime-web": "onnxruntime-web/dist/ort.min.js",
      },
    },
  },
};

export default nextConfig;
