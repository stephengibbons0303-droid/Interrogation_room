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

---

## 2026-07-21 — Moved speech fully local (Deepgram/OpenAI → pair C)

**Architecture decision: keep the STT → LLM → TTS pipeline. Unified speech-to-speech is
not yet the right choice for this app.**

Backed by a verified research pass (24 sources, 120 claims extracted, 25 adversarially
verified — 16 confirmed, 9 refuted). Every open S2S model fails at least one hard
requirement on 24 GB VRAM:

| Model | Fits 24 GB | Per-turn voice switch | Text + audio | Licence |
|---|---|---|---|---|
| Qwen3-Omni-30B-A3B | ✗ ~69–79 GB | ✓ | ✓ (cleanest) | ok |
| PersonaPlex ~7B | ✓ | ⚠ not demonstrated | ✓ (artifact-laden) | NVIDIA OML |
| Step-Audio-2-mini ~8B | ⚠ unverified | ✓ | ✗ unverified | ✓ Apache 2.0 |
| Covo-Audio ~8.4B | ⚠ | ✗ | ✗ | ✗ research-only |

No model offers a documented British male + female pair. Decisively, **Kyutai — who built
Moshi — ships its own product (Unmute) as a cascaded pipeline**, citing LLM reasoning,
function-calling and swappability: exactly what the interrogation logic depends on.

*What would flip this:* PersonaPlex demonstrating mid-conversation voice re-prompting plus
a live per-turn text channel. Also unevaluated: Qwen3.5-Omni (~Mar 2026).

### What was built
- `backend/speech/` — dedicated **speech pair C** sidecars, both OpenAI-compatible:
  - STT `:7677` — faster-whisper **large-v3 on CUDA** (not `small.en`; learners are
    non-native speakers and that is where the small English-only model degrades)
  - TTS `:7678` — Kokoro 82M, CPU, **British voices**: Reynolds `bm_george`,
    Chen `bf_isabella`
- `backend/main.py` — `/stt` and `/tts` now call the local sidecars. **Deepgram removed
  entirely; `DEEPGRAM_API_KEY` no longer needed.**
- Fixed two real bugs found by running it, not by reading it:
  - `frontend/app/api/tts/route.ts` hardcoded `Content-Type: audio/mpeg`, so the client
    tried to buffer Kokoro's WAV into an MP3 MediaSource → `NotSupportedError`.
  - `frontend/lib/speech.ts` chose the streaming path without checking content type.

### Verified working
Full loop through the real UI: chat → agent → TTS → decoded audio (no errors), and STT
round-trips verbatim ("Have a seat. State your full name for the record, please.").
STT ~1.0 s on GPU; TTS 3.5–4.5× faster than realtime.

### Open threads
- **LLM not wired.** Runs in Mock Mode. Decide GPT-4o vs local Ollama. Note the VRAM
  cost: `gemma4:26b` (18 GB) + large-v3 (~3 GB) will not comfortably share 24 GB.
- **Microphone never tested** — the Browser pane blocks capture. Needs a real browser.
  This is the one part of the chain still unproven end to end.
- **TTS has no streaming.** Kokoro synthesises the whole utterance first (~1.7 s of
  silence before a 20-word line). If pacing suffers, chunk by sentence.
- **Accented-L2 accuracy unvalidated** — large-v3 is the right call in principle, but
  has not been tested on real learner speech.
- `unmute_readme.md` in the repo root is stray research debris (Kyutai's README), not
  project content — safe to delete.

---

## 2026-07-21 — The game engine

Rebuilt the app around a real engine, from `documents/A structured taxonomy of real
interrogation techniques.md`. Roughly a quarter of that document had reached the code, and
only as vocabulary in the character prompts.

**Design rule: the engine decides *what* happens; the LLM decides *how* it is said.** One
structured call per turn returns the line, the tactic used, and what the learner committed
to — median **3.6s/turn**, unchanged from before.

### What exists now
- `scenario/` — the case with structured evidence (strength + the three Evidence Framing
  Matrix levels + what each item contradicts), and secret **briefs** dealt per session.
- `engine/timeline.py` — the Timeline Validator the design doc specified and never had.
- `engine/analysis.py` — CBCA/RM-lite content scoring; hedging and self-correction count as
  markers of *truthful* recall, per the research.
- `engine/tactics.py` — 17 techniques with PEACE stage gates, preconditions and cooldowns.
- `engine/director.py` — the five documented hand-off triggers (100% trigger-driven in
  simulation, vs a coin flip before), pressure, PEACE progression, outcomes.
- **The two-hander** — detectives confer in front of the learner; `Turn.addressed_to`
  distinguishes overheard from directed speech. Chen's arc is state
  (`neutral → rapport → advocate → identifying → minimising → sting`); the sting fires
  *only* when a claim she vouched for is the one that breaks.

### Rules the engine enforces
- **Language never raises pressure.** Errors, hesitation and short-but-responsive answers
  are ignored; only deliberate evasion counts.
- **Being disbelieved is not being caught lying.** Much of the evidence is circumstantial by
  design, so an honest, consistent account is *never* detained however bad it looks.
- **Never convict on inferred data.** Speech gives one time bound, not two; inferred spans
  measure coverage but cannot establish a contradiction.

### Verified
64 unit tests (no LLM). Three full interviews against Azure: consistent-innocent (not
detained, no lie inferred), self-contradicting (**detained**, evidence disclosed at
escalating framing, **reverse chronology fired**), monosyllabic learner (pressure stays low,
`rapport_repair` fires). Resume survives a full backend restart. Asides render as one wav
containing both voices, verified byte-exactly.

### Still open
- **Microphone remains the one untested link** — the automated browser blocks capture.
- Post-session KLP assessment and xAPI (deliberately deferred). `Turn.modality` and
  `addressed_to` and the `claims` table are already capturing what it will need.
- `released` is hard to reach on briefs where the case evidence points at the learner
  regardless; worth tuning once you have played it.
