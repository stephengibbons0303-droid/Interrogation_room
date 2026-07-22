# Code review — branch `claude/interrogation-repo-diff-0372f1` vs `main`

Max-effort local review, 2026-07-22. 10 finder angles → dedup → 9 adversarial
verifiers (many executing the failure against the real engine/DB) → gap sweep.
**41 findings confirmed, 0 refuted.** The top 15 are in the review UI; this file
is the complete set for the fix + simplify pass. Delete once cleared.

Severity: **C1** critical (security / data loss / core-broken) · **C2** high
(broken feature, real user harm) · **C3** medium (correctness, narrower) ·
**Q** quality (cleanup — never a merge blocker).

**Status: all nine C1 criticals FIXED** (commit on this branch; 211 engine tests,
both whole-interview simulations green, real DB migrated). The evidence-window
minute-clamp bug (finding 21) was fixed in passing with finding 2. C2/C3/Q remain
open for the next pass.

---

## C1 — Critical  ✅ all fixed

1. **JWT signing key defaults to a committed constant** — `backend/security.py:27`.
   `.env.example` never mentions `SECRET_KEY`. Anyone reaching the backend (LAN
   when `python main.py` binds 0.0.0.0) mints a valid token for any user id with
   the public key; every ownership check is moot. *[reported]*

2. **Evidence + timeline convict on invented (inferred) time bounds** —
   `director.py:507` (evidence pass) and `timeline.py:192-213` (overlap/impossible),
   neither guarding `claim.inferred`, unlike every sibling check. "got to the pub
   about nine" (start-only) → normalised end 23:59 → 3 evidence clashes for an
   unaccounted hour → `caught` → DETAINED. Founding-invariant violation. Design
   note: the outcome design *partly leans* on the collision, so fix = mint only
   when a **stated** bound overlaps, not a blind guard. No test notices either way. *[reported]*

3. **Acquiescing to the planted false premise convicts the learner** —
   `agent.py:356` (ingest before resolve_premise). Echoing the engine's own
   misquote mints a self-contradiction (+0.12), supersedes the true claim (store
   now holds the FALSE time), can spring Chen's sting. Breaks the documented
   "letting it slide costs NOTHING". Guard ingest against the open premise. *[reported]*

4. **Committed port defaults break a fresh clone** — `frontend/app/api/[...path]/route.ts:3`,
   `stt/route.ts:3`, `tts/route.ts:3`, and `main.py:138` all default to 8000;
   backend runs on 8013; the override is only in gitignored `.env.local`. Fresh
   clone can't sign in. Also a PORTS.md violation (8000 = SAIF). Fix: commit
   `frontend/.env.local` → `.env` defaults, or make main.py default 8013. *[reported]*

5. **Unattended open mic ratchets pressure and ends the interview** —
   `director.py:586` + silence path `agent.py:228`. Standing gaps/impossible are
   re-charged every `update_pressure` (not ledgered); [SILENCE] re-fires every
   4-8s running the full pipeline without a turn. Reaches CLOSURE at event ~17,
   nobody present, cooldowns drained by wall-clock. Ledger the artifact charge;
   don't run pressure on silence. *[reported]*

6. **`tactic_used` trusted without validation** — `agent.py:336`/`:372`. Phantom
   `challenge_contradiction` marks evidence raised → `caught` → DETAINED; echoed
   `reverse_chronology` burns the retelling budget and corrupts the baseline.
   Validate against the offered shortlist; fall back to options[0]. *[reported]*

7. **PROBE never exits for sparse accounts** — `director.py:661`. `report.complete`
   + the middle conjunct stay hard; `PROBE_PATIENCE` bypasses only density;
   `MAX_TURNS` lives only in the CHALLENGE branch. Verified over 80 turns: stage
   never leaves PROBE, outcome stays None, /chat accepts forever. Add a turn-based
   escape to PROBE. *[reported]*

8. **Agent cache races + survives failed commits** — `sessions.py:251`. Sync
   endpoint, threadpool-concurrent, lock guards only the dict, no (interview_id,
   seq) unique constraint, no drop-on-error. Concurrent chats last-write-wins on
   engine_state; a failed commit leaves the cached agent ahead of the DB. Per-
   interview lock + drop_agent on the error path + the unique constraint. *[reported]*

9. **Claims table never records supersession** — `sessions.py:277`. Insert-only,
   text-deduped; superseded_by/restates never update; place/topic/restates/inferred
   have no columns. Live DB: 27 superseded + 12 restatements in engine state, **0**
   in the table the KLP assessment reads. Upsert by claim id; add the columns. *[reported]*

---

## C2 — High

10. **SUE evidence system largely inert** — `case.py:215` filter excludes 7/10
    items (6 with no route at all, incl. `phone_records` that `canal_meeting`'s
    brief promises "will not work" to deny); `next_disclosure` vague→moderate→precise
    escalation unreachable (`director.py:832`); `_evidence_block` (`prompts.py:110`)
    shows the precise fact regardless of framing level; `DISCLOSURE_ORDER` +
    `requires_commitment` dead. *[reported, merged]*

11. **speech.ts VAD lifecycle** — `speech.ts:172`. Rejected `_initVAD` latches
    `vadReady` (mic dead for the session); `destroy()` never resets it nor re-checks
    after awaits; **vad-web 0.0.30 ignores the `stream` option and always opens a
    second getUserMedia stream** — so two mic streams run normally, and a hot mic
    survives unmount. *[reported, merged SP1+SP3]*

12. **stopAudio drops the pending onEnd** — `speech.ts:282`. Interrupting the
    closing line → outcome screen never renders, room stays interactive, next send
    hits 409 mislabeled "Connection to server failed". Blob URL leaks on every
    interrupt. Fire onEnd + revoke in stopAudio; disable MIC/PLAY while speaking. *[reported]*

13. **LLM failure persists the mock line as a real turn** — `agent.py:280`. One
    Azure timeout writes "[MOCK MODE …] The detectives study you in silence." into
    the transcript (fourth-wall break, read aloud, assessed), 200 OK, loses that
    turn's claims, desyncs cached history from DB. Don't persist mock turns; 503
    instead. *[reported]*

14. **Reviewing a completed interview is impossible** — `InterrogationRoom.tsx:458`.
    Outcome card returns before the transcript JSX; `outcome` never reset. Render
    the transcript with the outcome as a header/banner. *[reported]*

15. **`topic_complete` undocumented → topics_covered starves** — `agent.py:166`.
    No Field description, never mentioned in the extraction prompt. Live DB: 8/13
    interviews have zero topics; the ≥3 stage-gate limb has never fired. Kills a
    hand-off trigger, `topic_switch`, and a PROBE-exit path. *[reported]*

16. **React StrictMode kills "Read it to me" in dev** — `BriefingScreen.tsx:33`.
    The `gone` ref is poisoned at mount by StrictMode's cleanup double-invoke and
    never reset, so **every** narration click in `npm run dev` synthesises then
    silently discards the audio. Reset `gone.current=false` in the effect body. *[cut by cap]*

17. **db.py legacy NOT NULL column drop can 500 new interviews** — `db.py:234`.
    A swallowed DROP COLUMN leaves `escalation_score`/`contradiction_count` NOT
    NULL with no server default; every `create_interview` then IntegrityErrors.
    Bites on old system SQLite (<3.35: Ubuntu 20.04, Debian 11, RHEL 8), not this
    venv (3.53). Recreate the table, or make the columns nullable server-side. *[cut by cap]*

18. **Token refresh clears tokens on any non-OK, incl. 502** — `api.ts:150`.
    Access token expires during a backend blip → refresh 502s → both tokens wiped,
    silent sign-out mid-interview though the refresh token was valid. Clear only on
    401/403 from the backend. *[cut by cap]*

19. **Delete has no confirmation** — `InterviewPicker.tsx:197`. The ✕ beside
    Resume/Review cascade-deletes turns+claims+engine state on one misclick, no
    undo; double-click 404s into the error banner. Add a confirm + disabled state. *[cut by cap]*

---

## C3 — Medium

20. **`_retelling_conflicts` blind to free-text `place`** — `director.py:299`.
    Only `location` is compared, and self-checks are skipped during a retelling, so
    moving "the pub"→"the restaurant" (both location=None — most claims) is missed
    *during the exact test built to catch substitutions*. Use `place_key`/`same_place`. *[cut by cap]*

21. **Evidence-window clamp: minute term unclamped** — `director.py:505`.
    `end_min=1440` → time(23,00) not 23:59 (−59 min); a fully-stated after-midnight
    span expands/inverts the window. Latent (no eligible evidence past 22:20 today).
    Use `timeline.fmt`/clamp both terms. *[cut by cap]*

22. **[SILENCE] turns unpersisted → rehydrated history diverges** — `sessions.py:258`
    skips the user row while `agent.py:226` appends it, so post-eviction LLM context
    differs from live. Persist silence turns (flagged) or strip them from live history. *[cut by cap]*

23. **Hard-coded opening line never persisted** — `InterrogationRoom.tsx:290`.
    Client-only; on resume the transcript starts with the learner answering an absent
    question. Write it as the first Turn row at interview creation. *[cut by cap]*

24. **`/tts` + `/stt` unauthenticated, unbounded body** — `main.py:71`. With
    0.0.0.0 + wildcard CORS, any LAN/cross-origin caller burns the GPU/CPU models;
    `/stt` reads an unbounded upload into memory. Auth them; cap the size. *[cut by cap]*

25. **Old `[Reynolds]:` self-label strip dropped** — `agent.py:304`. The rewrite
    removed the guard while still feeding the model its own lines as `[Name]: text`;
    a mimicked label renders in the bubble and is read aloud, compounding on re-feed.
    Restore the strip. *[cut by cap]*

26. **`onResult` unconditionally wipes the shared error banner** — `InterrogationRoom.tsx:240`.
    A successful transcription clears TTS_SILENT (and any net-error) though detective
    audio is still broken. Clear by source, not blanket. Usually a flicker; permanent
    when the underlying error was the network one. *[cut by cap]*

27. **Aside format keyed off only the first shortlisted tactic** — `agent.py:248`.
    `detective_aside` at position 2-3 can be reported without the 3-utterance
    contract (stranding the learner); or the format is imposed when it's first but
    unused. Key the aside prompt off the reported tactic. *[cut by cap]*

28. **`exculpation` + `premises_caught/missed` written, never read** — `director.py:598/812`.
    The documented "counterweight" and the +0.08 premise-catch credit change no
    outcome; catching a false premise has zero effect. Either consume in
    decide_outcome or delete. *[cut by cap]*

---

## Q — Quality (cleanup — for the /simplify pass, not merge blockers)

29. **ingest re-normalises the claim store per new claim** — `director.py:412`,
    `_first_telling:184`, duplicating the `spans` built at :380. Bind `norm` once.
    ~1,260 redundant dataclass copies/turn by turn 40. *[C1]*

30. **timeline.build runs twice per message** — `agent.py:242` + `director.py:844`,
    ~19k redundant pair comparisons/message. Build once, pass into build_context. *[C2]*

31. **density.assess re-runs the 7-regex analyse over all claims ×4/turn** —
    `density.py:167`. ~3,160 regex scans/turn by turn 30. Cache sensory on the Claim
    at ingest; thread one assess through Context. *[C3]*

32. **sessions N+1 / full-transcript loads** — `_summary:156` loads every
    interview's turns for an 80-char preview (picker landing view); `chat` does
    `len(iv.turns)` + `{c.text for c in iv.claims}` per message. Count query;
    persist a preview column. *[C4]*

33. **Dead code** — `STAGE_ORDER` import (`director.py:16`), `live_claims`/`vouched_claims`
    (`state.py:215/225`), ingest's unread `analysis` param (`director.py:326`),
    write-only premise counters. Delete. *[C5 + simplification]*

34. **Audio lifecycle triplicated & drifted** — `speech.ts` playAudio vs
    playStreamingAudio vs `BriefingScreen.speak`; blob path reports errors, the
    other two are silent. Extract one `attachPlayback`/`playBlob`. *[C6 + reuse]*

35. **Concealment card duplicated + double brief fetch** — `BriefPanel.tsx:52` ≈
    `BriefingScreen.tsx:126`; both GET `/interviews/{id}/brief`. Shared component;
    fetch once in InterrogationRoom and pass down. *[C7 + reuse]*

36. **`same_place` misfires both ways** — `director.py:218`. Merges "Angel cafe"/
    "Angel station" (shared district token) yet still fails "the pub"/"Pig & Whistle"
    — the pair its own docstring cites. Resolve place identity once, at extraction. *[C8 + altitude]*

37. **Span-merge + overlap math duplicated** — `_covered_minutes` (`director.py:236`)
    re-implements `timeline.build`'s merge; `min(end)-max(start)` hand-typed 3× in
    director + variants in timeline/case. Extract `merge_spans`/`overlap_minutes`. *[reuse]*

38. **minutes↔time conversions re-derived** — `briefs.py:74` `window_min`,
    `director.py:505` inline time-rebuild, vs `timeline.to_min`/`fmt`. Centralise. *[reuse]*

39. **Four copies of `BACKEND_URL` + raw `/tts` `/stt` fetches** — BriefingScreen,
    InterrogationRoom, speech.ts bypass `lib/api.ts`; when audio gains auth they
    won't refresh-retry. Route through an exported `apiFetch`. *[reuse]*

40. **`_LEAVING_RX`/`_ARRIVING_RX` departure-sniffing is a bandaid** — `director.py:64`.
    Regex text-matching re-guesses start/end the extractor should own. Give ClaimOut
    an explicit arrival/departure/span semantics field. Each new phrasing grows the
    regex. *[altitude]*

41. **prompts.build_system_prompt takes 4 loose Context fields + `_apply` threads
    `offered_premise`** — `prompts.py:179`, `agent.py:298`. Pass the Context. Adding
    one prompt datum currently means 5 edits. *[simplification]*

---

### Cross-cutting root causes (fix these and several findings collapse)

- **Never convict on inferred bounds** — findings 2, 5(partial), 20, 21. One guard
  helper (`stated bounds only`) applied at every mint site.
- **The persisted record is not the engine's** — 9, 13, 22, 23, and the assessment
  substrate generally. Persistence needs to mirror engine_state (upsert, silence
  turns, opening line), not approximate it.
- **The model's self-report is trusted** — 6, 27. Validate `tactic_used` against the
  shortlist once, at the boundary.
- **`topic_complete` never set** — 15, and it compounds the PROBE trap (7).
