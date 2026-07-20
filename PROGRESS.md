# Progress Log

## 2026-07-20 — Repo vs. GitHub vs. Railway deploy check

**Question:** Is there a diff between the local repo and the version deployed from GitHub (Railway)?

**Conclusion: No meaningful diff — repo, GitHub, and the live Railway frontend are all in sync.**

### What was checked
- **Git level:** local worktree, local `main`, and `origin/main` all on commit `f71bfce` (0 ahead / 0 behind, clean tree).
- **Live frontend:** https://interrogationfrontend-production.up.railway.app/ (Railway, Next.js).
  - Start screen matches `frontend/components/InterrogationRoom.tsx` exactly.
  - Discriminating test: the ORT `.mjs` backend wrappers (`/ort-wasm-simd-threaded.mjs`, `.jsep.mjs`) are served with 200. These are only produced by the prebuild script **after** commit `d98b532` ("Copy ORT .mjs backend wrappers alongside .wasm binaries"), so the deploy is built from the current `HEAD`, not a stale build.

### Open thread for next session
- **Backend not yet compared.** It's a separate Railway resource; only the frontend URL was available. Frontend talks to it via `/api` (proxied through `NEXT_PUBLIC_BACKEND_URL`). Need the backend service URL to verify it against the repo.

### Reference docs in repo
- `README.md` — project overview + roadmap/to-do checklist.
- `interrogation_learning_system.md` — full design spec (theory + 8-agent architecture).
