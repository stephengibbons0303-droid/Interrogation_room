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
};

export default nextConfig;
