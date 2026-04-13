#!/usr/bin/env node
/**
 * Copies the static assets required by @ricky0123/vad-web into public/
 * so they can be served by Next.js at runtime.
 *
 * Assets needed:
 *   - vad.worklet.bundle.min.js  (AudioWorklet)
 *   - silero_vad.onnx            (VAD model — searched recursively in the package)
 *   - ort-wasm-*.wasm            (ONNX Runtime WASM binaries)
 */

const fs   = require("fs");
const path = require("path");

const root      = path.join(__dirname, "..");
const publicDir = path.join(root, "public");
const vadRoot   = path.join(root, "node_modules", "@ricky0123", "vad-web");
const ortDist   = path.join(root, "node_modules", "onnxruntime-web", "dist");

// ── helpers ──────────────────────────────────────────────────────────────────

function cp(src, destName) {
  if (!fs.existsSync(src)) {
    console.warn(`[copy-vad-assets] Warning: not found – ${src}`);
    return false;
  }
  fs.copyFileSync(src, path.join(publicDir, destName));
  console.log(`[copy-vad-assets] Copied ${destName}`);
  return true;
}

/** Recursively find the first file whose name matches `predicate` under `dir`. */
function findFirst(dir, predicate) {
  if (!fs.existsSync(dir)) return null;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      const found = findFirst(full, predicate);
      if (found) return found;
    } else if (predicate(entry.name)) {
      return full;
    }
  }
  return null;
}

// ── 1. AudioWorklet bundle ────────────────────────────────────────────────────
cp(
  path.join(vadRoot, "dist", "vad.worklet.bundle.min.js"),
  "vad.worklet.bundle.min.js"
);

// ── 2. Silero VAD ONNX model ──────────────────────────────────────────────────
// The model file is not always at a fixed path in the npm package —
// search the whole package directory for any .onnx file.
const onnxSrc = findFirst(vadRoot, (name) => name.endsWith(".onnx"));
if (onnxSrc) {
  fs.copyFileSync(onnxSrc, path.join(publicDir, "silero_vad.onnx"));
  console.log(`[copy-vad-assets] Copied silero_vad.onnx (from ${path.relative(root, onnxSrc)})`);
} else {
  console.warn(
    "[copy-vad-assets] Warning: silero_vad.onnx not found in the package. " +
    "The library will attempt to fetch the model from its default CDN URL."
  );
}

// ── 3. ONNX Runtime WASM binaries ────────────────────────────────────────────
if (fs.existsSync(ortDist)) {
  for (const file of fs.readdirSync(ortDist)) {
    if (file.endsWith(".wasm")) {
      cp(path.join(ortDist, file), file);
    }
  }
} else {
  console.warn("[copy-vad-assets] Warning: onnxruntime-web/dist not found.");
}
