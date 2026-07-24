# Design note: episodic detail, and the phone thread

Captured 2026-07-23, from a playtest of the concealment-pair build. Two
observations from one interview that turn out to be the same problem.

> **STATUS (2026-07-24) — fully built (phases 1, 2 and 3).**
>
> **Phase 1 (episodic/procedural), built:** via option (a) below — the extractor
> tags each claim (`ClaimOut.episodic`, documented in the extraction prompt),
> carried on `engine.state.Claim`, persisted on `db.Claim`, and `density.testable()`
> now counts **episodic claims only**. Procedural detail still earns richness and
> exculpation everywhere else. Defaults to episodic so an untagged extraction
> behaves exactly as before.
>
> **Phase 2 (empty-evening soft signal), built:** `density.has_contact()` detects
> whether the account mentions anyone or any call/text; `prompts._state_block`
> surfaces a "NO CONTACT" hook once there is an account with none in it. It is a
> prompt hint only — never touches pressure or the outcome, and an honest
> contactless evening still walks (tests pin both).
>
> **Phase 3 (phone tactics), built:** `phone_absence_hook` (PROBE; fires on a
> contactless account; one-shot via `state.phone_probed`) and `phone_verifiability`
> (PROBE + CHALLENGE; needs a call/text/message on the record via
> `density.mentioned_comms`; one-shot via `state.phone_reminder_spent`, backed by the
> real referenceable `phone_records` evidence). `elicit_sequence` now foregrounds
> phone activity as the most anchored seam. Engine decides WHEN (preconditions + the
> one-shot ledger); the model delivers the line, false_premise-style. Both flags
> round-trip through `to_dict`/`from_dict`.
>
> **PEACE placement (was the open question below), settled and implemented:** hook +
> anchoring in PROBE, the verifiability reminder in PROBE *and* CHALLENGE.
>
> **Open question below: settled.** PEACE placement is hook + anchoring in PROBE,
> with the verifiability reminder available in PROBE *and* CHALLENGE — it follows a
> commitment whenever that lands, and "that can be checked" has challenge character.

## What the playtest showed

The learner played an innocent-at-home evening and narrated it well: came in,
keys on the table, shoes on the rack, sat on the sofa, put the TV back on,
watched *Tall Pines* on Netflix. Rich, fluent, procedural language - exactly what
the app exists to elicit.

The detectives pressed in two ways, and both fell flat:

1. **"Who would have seen you? Who did you speak to?"** The honest answer is a
   shrug - "I can't speak for other people, I didn't talk to anyone" - and a
   shrug costs nothing. Asked more than once, it reads as the interview spinning.

2. **"A witness saw a man near the canal; you say you were home. Help me with
   that."** The clash is legitimate (the account genuinely collides with the
   mast), but the *delivery* is the model improvising the blandest possible
   line, and the follow-up is the same toothless "who saw you".

The learner's own diagnosis, which is correct: **the corroboration question has
no teeth, and the rich detail I gave has no jeopardy in it, because I was
describing what I *always* do coming through my own front door - I could
reproduce that word-for-word next week.**

## The deeper problem: episodic vs procedural detail

The engine scores detail density - sensory words, named people, activities,
timepoints (`engine/density.py`) - and treats all detail the same. But there are
two kinds, and only one carries game value:

- **Episodic** - specific to *that* night, anchored to a time or an external
  event: "a text came in about quarter past eight", "the episode ended and it
  said 10:20". Hard to reproduce identically when the account is run backwards.
  This is where jeopardy lives.

- **Procedural / habitual** - "what I always do": keys, shoes, sofa, TV. A
  rehearsed script the learner reproduces perfectly every time *by definition*.
  It cannot produce the delta-between-tellings that `_retelling_conflicts`
  exists to catch.

So a learner who narrates their habitual routine beautifully scores as a rich,
"testable" account (`density.testable`) - and then the second telling finds
nothing, because habit is consistent by nature. From the **app's** side this is
a win: the learner is producing exactly the descriptive and procedural language
the app is for. From the **game's** side the detail is *rewarded but not
weaponised* - the engine cannot tell "I always do this" from "this happened that
night", so it banks procedural narration as if it were checkable.

This is the gap. Rich language is being produced and not converted into jeopardy.

## The phone thread - the fix for both problems at once

Phone activity is inherently **episodic, timestamped, and verifiable** - the
three properties the corroboration question lacked and the retelling mechanic
feeds on. It drags the interview off habitual-routine ground and onto checkable
ground. Three moves, escalating:

### 1. The suspicious-absence hook

"You spoke to nobody, messaged nobody, all evening?" An empty-phone evening is
not proof of anything - but it is a *pattern* worth pressing, because everyone is
on their phone. The point of the hook is not the absence itself; it is that
discomfort makes the learner **volunteer a commitment** where there was only a
shrug: "well, actually I did text someone." A shrug becomes a checkable fact.

### 2. The verifiability reminder

Once they have committed: "those records exist - are you certain?", with the
implicit "it will look very bad if this turns out to be invented." This is the
move that attaches a *cost* to a free-text claim. It is the honest-but-awkward
pressure the concealing brief already trades in, pointed at something the police
can actually check.

The case already holds the material: `phone_records` (Emily called the subject
at 4:12 and 7:58) exists in `scenario/case.py`, and as of the SUE fix it is
*referenceable* by the detectives during Challenge (`case.referenceable_evidence`).
So the reminder is not a bluff - there is real phone evidence on file.

### 3. Phone-as-timeline-anchor

"How often were you on your phone? What were you looking at while the show was
on? On the walk?" Each answer is a **timestamped, checkable event** - which is
exactly what `elicit_sequence` is starving for (it presses for clock anchors and
an account of habitual routine gives it almost none). Phone usage manufactures
the points on the timeline that reverse-chronology and the false-premise probe
then bite on.

## How this connects to what exists

- `density.timepoints()` / `elicit_sequence` already want more clock anchors;
  phone activity is a natural, plentiful source of them.
- `_retelling_conflicts` already scores a stated time that slid or a name that
  swapped; a "text at 8:15" that becomes "8:40" on the second telling is caught
  for free once it is a stored claim.
- `phone_records` evidence already exists and is already referenceable; the
  verifiability reminder has something true behind it.
- The concealing brief's whole logic - a fact to hide, a cover to hold - is
  sharper when the cover has to survive against records rather than against
  "nobody can confirm it either way".

## What is new, and needs building

- **An episodic / procedural distinction in the scorer.** Two candidate
  approaches: (a) the extractor tags each claim as episodic-vs-habitual (the
  model can judge "specific to that night" vs "a general routine", the way it
  already tags `topic` and `responsive`); or (b) the engine infers it - a claim
  with a stated clock time or a named external event is episodic, a timeless
  present-habitual description is procedural. Option (a) is cleaner and cheaper.
  Either way, **procedural detail should stop counting toward `density.testable`**
  - it can still earn language credit, but it must not make an account read as
  worth attacking when there is nothing in it to catch.

- **A corroboration / phone tactic** carrying the three moves, with a little
  engine state: has phone activity been probed; did they claim an empty evening
  (the hook is armed); has the verifiability reminder been spent. Modelled on
  how `false_premise` is planned in the engine and merely *delivered* by the
  model.

- **Empty-evening as a soft signal.** An account with no messages, no calls, no
  contact of any kind is not a contradiction and must never be scored as a lie -
  but it is a legitimate thing for the detectives to lean on, and worth surfacing
  to them the way thin topics already are.

## What must not change

- **Language quality never raises pressure.** A learner who produces rich
  procedural language is doing the thing the app exists to elicit. Declining to
  *weaponise* procedural detail is not the same as penalising it - it still earns
  exculpation and it is still good practice. The distinction only governs whether
  the engine treats the account as *testable*, never whether the learner is
  doing well.

- **Never convict on the absence.** "I messaged nobody" is a suspect pattern, a
  hook, a reason to press - it is not evidence of fabrication, and an honest
  hermit's quiet evening must still be able to walk.

## Open question

Does the phone thread want its own PEACE placement, or is it just extraction
(sub-phase 3b) aimed at a richer vein? Probably the latter - it is funnel
questioning that happens to mine the most verifiable seam available - but the
hook-and-reflect rhythm (absence -> commitment -> "that can be checked") has a
challenge-phase character to it too. Worth deciding before it is wired, because
it changes which stage gates it.
