#!/usr/bin/env node
/**
 * Copies the static assets required by @ricky0123/vad-web into public/
 * so they can be served by Next.js at runtime.
 *
 * @ricky0123/vad-web uses ONNX Runtime Web (ort) which requires:
 *   - An AudioWorklet bundle (vad.worklet.bundle.min.js)
 *   - A Silero VAD ONNX model (silero_vad.onnx)
 *   - ONNX Runtime WASM binaries (ort-wasm-simd-threaded.wasm, etc.)
 *
 * These must be served from the app origin, and SharedArrayBuffer (needed
 * by the threaded WASM build) requires the COOP/COEP headers set in
 * next.config.ts.
 */

const fs = require("fs");
const path = require("path");

const publicDir = path.join(__dirname, "..", "public");

const copies = [
  // VAD AudioWorklet + ONNX model
  [
    "node_modules/@ricky0123/vad-web/dist/vad.worklet.bundle.min.js",
    "vad.worklet.bundle.min.js",
  ],
  [
    "node_modules/@ricky0123/vad-web/dist/silero_vad.onnx",
    "silero_vad.onnx",
  ],
];

// Also copy every ort *.wasm file from onnxruntime-web
const ortDist = path.join(__dirname, "..", "node_modules", "onnxruntime-web", "dist");
if (fs.existsSync(ortDist)) {
  for (const file of fs.readdirSync(ortDist)) {
    if (file.endsWith(".wasm")) {
      copies.push([path.join("node_modules/onnxruntime-web/dist", file), file]);
    }
  }
}

for (const [src, dest] of copies) {
  const srcPath = path.join(__dirname, "..", src);
  const destPath = path.join(publicDir, dest);
  if (!fs.existsSync(srcPath)) {
    console.warn(`[copy-vad-assets] Warning: source not found: ${srcPath}`);
    continue;
  }
  fs.copyFileSync(srcPath, destPath);
  console.log(`[copy-vad-assets] Copied ${dest}`);
}
