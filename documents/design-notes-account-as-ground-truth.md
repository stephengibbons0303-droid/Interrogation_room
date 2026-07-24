# Design note: the learner's own account as ground truth

Captured 2026-07-21, after the first real playtest of the engine.

> **BUILT (confirmed 2026-07-24).** Everything in "What is new" below now exists:
> detail density per topic (`engine/density.py`), re-telling mode
> (`director.arm_retelling` / `_retelling_conflicts`), false-premise generation and
> scoring (`director.plan_false_premise` / `resolve_premise`), and `scenario/briefs.py`
> reduced to an entangled denial + substitution pair. The header used to say "not yet
> built"; the in-line notes dated 2026-07-22 were written during the build. Kept as
> the design rationale for why the engine is shaped this way.

## The problem this solves

The engine works, but the room does not feel dangerous. The techniques fire
correctly into a vacuum.

The cause is that the source of truth is a card with five short lines on it. A
real interview is punishing because you are reconstructing a genuinely complex
evening from memory: the peripheral detail is endless, and either recalling it
accurately or fabricating it consistently is hard work. **You cannot be pinned
down on detail you were never given.** Unanticipated questions, reverse
chronology and anchoring all need something to bite on.

The obvious fix - a much richer brief - fights the constraint that made it short
in the first place: a second-language learner holding pages of facts is being
given a memory test, not a language test.

## The shift

Stop issuing an account. Let the learner build one.

They are asked about their evening and it is theirs to invent. The detectives
extract detail from them, and *that detail becomes the ground truth the engine
tests them against*. Nobody memorises a stranger's card; they are recalling their
own invention, which is exactly the cognitive task a real interviewee faces.

## Three mechanics

### 1. Extraction — probe until the account is testable

The middle phase is not about catching anyone. It is about manufacturing the
material to attack later. "A restaurant? What did you eat? Was it busy? Who
served you?"

This is PEACE sub-phase 3b, and the taxonomy is explicit that funnel questioning
exists to generate *"checkable facts and provable lies"* - the more detail
obtained, the more verifiable or falsifiable the account becomes.

The engine can drive this measurably rather than by feel: it knows a given
time-block has two entities, no sensory detail and no named people, so it knows
that block is thin and worth pressing. **Detail density per topic becomes a
first-class engine signal**, and probing continues until a block is rich enough
to be worth testing.

### 2. The second telling is the test

Once the account is rich, ask for it again - backwards, or outward from a fixed
point. The jeopardy is simply **the delta between telling one and telling two**.

Vrij et al. (2008): liars find reverse recall far harder because they rehearsed
forwards; observer detection accuracy rose from 42% to 60%. It is demanding for
truth-tellers too, which is the point - the difficulty is real either way, and
what separates them is whether the *content* holds.

The engine already stores structured claims and already detects contradictions
between them. What it lacks is knowing that it is now hearing a **re-telling**
rather than new information, so that a difference is scored as an inconsistency
rather than filed as another fact.

### 3. The false-premise probe

*"You said you left the cafe before eight?"* - when they actually said after.

The engine knows exactly what was said, so it can generate the misstatement
deliberately and score whether the learner corrected it. This is the sharpest
mechanic available and it is nearly free, because the claim store already exists.

It doubles as genuine assessment signal: spontaneous correction is a CBCA
criterion for truthful accounts, so "did they catch it" is data, not just drama.

Interleave it with topic switching mid-recall - ask about someone never
mentioned, how they met, then snap back to the timeline - and that is the
cognitive-load stack the taxonomy describes, assembled from parts the engine
mostly has.

## What this quietly fixes

With the learner's own account as ground truth they can never be *wrong*, only
*inconsistent*. That dissolves the fairness problem hit during the build, where
an honest learner was detained over circumstantial evidence: there is no longer
an external truth for them to be wrong about, so pressure can only come from
their own account moving.

### Except that it does not dissolve on its own

Found while building it, 2026-07-22. The concealment pair puts a small external
truth back, and the case evidence corroborates it. Every item that can clash -
`cell_tower`, `witness_sighting`, `cctv_figure` - sits at the bridge between
21:15 and 22:20, which is the same span the denial covers. So any cover story
collides with the mast data *by construction*: concealing perfectly and
concealing badly look identical from the evidence alone.

Left there, the only route to `released` was to give no account of that hour at
all - saying as little as possible as the winning strategy, which is the exact
opposite of the point.

So the collision does not decide the ending. It is what the interview *feels*
like; the verdict is made of what the learner did with their own account -
whether they conceded it, whether it moved under them, whether they would talk
at all. `decide_outcome` says so explicitly, and the test that pins it is
"a consistent account walks even when the evidence looks terrible".

## Decision: two things to conceal

Settled 2026-07-22. Pure consistency is fair and generates real load, but a lie
gives sharper jeopardy, so the concealment goal stays - and it is **two** fixed
facts, not one. The learner invents the evening freely; their invention has to
route around both.

Count is the weaker half of that decision. Two unrelated secrets - "you were at
the canal" and "you had been drinking" - are two things to dodge independently,
and the difficulty adds rather than compounds. **Two secrets drawn from the same
episode multiply**, because the cover invented for the first has to survive the
questions aimed at the second.

So the pair is entangled by construction, and the two halves are deliberately
different kinds of work:

- **A denial** - a fact to keep out. *You were on the towpath at 9:40.*
- **A substitution** - the hole that leaves, which has to be filled and then
  held. *So where were you instead, and who with?*

A denial can survive on omission if nobody presses. A substitution cannot: it
has to be produced on demand and then kept identical every time it is revisited.
That is where the load actually sits, and it is language work rather than memory
work.

It also costs nothing to test. The fabricated alternative enters the claim store
alongside everything else, so the second telling and the false-premise probe
bite on the invented half automatically - no new machinery for the sharpest part
of it.

### Why the memory objection does not apply here

The original argument for a single item was that a learner holding facts under
time pressure is being given a memory test. That guards against the wrong cost.
The brief is on screen for the whole interview and always has been - `BriefPanel`
keeps it deliberately unhidden, on the grounds that remembering bullet points is
not the exercise. Recall is already close to free. What a second secret adds is
inventing and holding, which *is* the exercise.

### What this does not change

The account is still theirs, and these two facts are the only external truths in
it. Pressure still comes from their own account moving rather than from the
engine knowing better: being disbelieved is not being caught, and inferred spans
still cannot establish a contradiction.

## What already exists

- Structured claims with time, location, activity and people (`db.Claim`,
  `engine.state.Claim`)
- Contradiction detection between claims (`director.ingest`)
- Timeline validator with gaps, overlaps and impossible journeys
- Tactics with preconditions and cooldowns, including `reverse_chronology`,
  `topic_switch`, `unanticipated_question`, `anchor_commitment`
- Content analysis that already counts sensory detail, corrections and hedging

## What is new

- **Detail density per topic**, to drive probing toward thin areas
- **Re-telling mode**, so a second pass is compared rather than accumulated
- **False-premise generation**, and scoring whether it was corrected
- Reducing `scenario/briefs.py` from a dealt account to an entangled concealment
  pair - one denial, one substitution
