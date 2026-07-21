# Design note: the learner's own account as ground truth

Captured 2026-07-21, after the first real playtest of the engine. Not yet built.

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

## Open question

**Do we keep a concealment goal?**

Pure consistency is fair and generates real load, but a lie gives sharper
jeopardy. A hybrid looks strongest: the learner invents the whole evening
freely, but is told **one** fixed thing to hide - "you were near the canal at
9:40, do not admit it". Everything else is theirs; their invention simply has to
route around that single fact.

That keeps the memory burden at one item while restoring a reason to be evasive.

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
- Retiring or reducing `scenario/briefs.py` to at most a single concealment fact
