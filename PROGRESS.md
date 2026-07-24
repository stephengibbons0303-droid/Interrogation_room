# Progress Log

## 2026-07-20 — Repo vs. GitHub vs. Railway deploy check

> **SUPERSEDED (2026-07-24).** The project no longer deploys to Railway; it runs
> locally against Azure OpenAI. The Railway URL below is dead and the deploy
> comparison no longer applies. Kept as history — see the 2026-07-24 entry.

**Question:** Is there a diff between the local repo and the version deployed from GitHub (Railway)?

**Conclusion: No meaningful diff — repo, GitHub, and the live Railway frontend are all in sync.**

### What was checked
- **Git level:** local worktree, local `main`, and `origin/main` all on commit `f71bfce` (0 ahead / 0 behind, clean tree).
- **Live frontend:** https://interrogationfrontend-production.up.railway.app/ (Railway, Next.js).
  - Start screen matches `frontend/components/InterrogationRoom.tsx` exactly.
  - Discriminating test: the ORT `.mjs` backend wrappers (`/ort-wasm-simd-threaded.mjs`, `.jsep.mjs`) are served with 200. These are only produced by the prebuild script **after** commit `d98b532` ("Copy ORT .mjs backend wrappers alongside .wasm binaries"), so the deploy is built from the current `HEAD`, not a stale build.

### Open thread for next session
- ~~**Backend not yet compared.**~~ **Obsolete (2026-07-24)** — there is no Railway backend to compare against. The backend runs locally on 8013.

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
- ~~**LLM not wired.**~~ **Resolved (2026-07-24)** — running on Azure OpenAI via
  `AZURE_OPENAI_DEPLOYMENT` (see `backend/.env.example`). Mock Mode survives only as
  the no-key fallback for a fresh clone. Local Ollama was not taken up, so the VRAM
  trade-off no longer applies.
- **Microphone never tested** — the Browser pane blocks capture. Needs a real browser.
  This is the one part of the chain still unproven end to end.
- **TTS has no streaming.** Kokoro synthesises the whole utterance first (~1.7 s of
  silence before a 20-word line). If pacing suffers, chunk by sentence.
- **Accented-L2 accuracy unvalidated** — large-v3 is the right call in principle, but
  has not been tested on real learner speech.
- ~~`unmute_readme.md` is stray research debris — safe to delete.~~ **Done** — deleted.

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

---

## 2026-07-24 — Off Railway; local + Azure OpenAI, and the review cleared

**Where this runs now: entirely locally.** There is no Railway deployment. The
2026-07-20 entry above is history, not current state.

- **LLM:** Azure OpenAI, deployment set by `AZURE_OPENAI_DEPLOYMENT` in
  `backend/.env` (see `backend/.env.example`). Mock Mode remains only as the
  no-key fallback so a fresh clone still boots.
- **Speech:** unchanged — the local pair-C sidecars, STT `:7677` (faster-whisper
  large-v3, CUDA) and TTS `:7678` (Kokoro, CPU, British voices).
- **Ports:** backend 8013, frontend 5185 (this repo's reserved pair; see CLAUDE.md
  and `~/.claude/PORTS.md`).

### The code review is fully cleared
All 41 findings from the max-effort review are resolved: nine C1 criticals, ten C2
highs, nine C3 mediums, and the Q cleanup pass (10 applied, 3 skipped with reasons
recorded in `CODE_REVIEW_FINDINGS.md`). 222 engine tests pass; the frontend
typechecks. Nothing was parked as tech debt.

### Still open
- **Microphone never tested end to end** — the automated browser blocks capture.
  Still the one unproven link in the chain. Needs a real browser.
- **TTS has no streaming** — Kokoro synthesises the whole utterance first.
- **Accented-L2 STT accuracy unvalidated** on real learner speech.
- **Post-session KLP assessment / xAPI** — deliberately deferred. The claims table,
  `Turn.modality` and `addressed_to` already capture what it will need.
- **Two design notes outstanding.** `design-notes-episodic-detail-and-the-phone.md`
  is not yet built (episodic-vs-procedural scoring, the phone thread).
  `design-notes-account-as-ground-truth.md` IS built — its header was stale.
