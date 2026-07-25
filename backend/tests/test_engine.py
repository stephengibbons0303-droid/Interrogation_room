"""Engine unit tests. No LLM, no network, no database.

Run:  backend/.venv/Scripts/python.exe backend/tests/test_engine.py

Deliberately dependency-free - the project has no test framework yet and this
should not be the change that introduces one.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import timeline as tl                       # noqa: E402
from engine.analysis import analyse                     # noqa: E402
from engine.state import Claim                          # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}{'' if cond else '  <- ' + detail}")


def block(cid, start_h, start_m, end_h, end_m, loc, text="", seq=1):
    return Claim(id=cid, turn_seq=seq, text=text or cid,
                 start_min=start_h * 60 + start_m, end_min=end_h * 60 + end_m,
                 location=loc)


def probed(cid, start_h, start_m, end_h, end_m, loc, topic, seq=1):
    """A claim with substance in it: a place, a time, somebody named, something
    done and something sensory. What a topic looks like after it has been probed,
    as against the bare assertions `block` produces."""
    return Claim(id=cid, turn_seq=seq,
                 text=f"{cid} - it was loud in there and I saw the barman",
                 start_min=start_h * 60 + start_m, end_min=end_h * 60 + end_m,
                 location=loc, activity="waiting", people=["Sam"], topic=topic)


print("\nTIMELINE VALIDATOR")

# Full account, no problems.
r = tl.build([block("a", 17, 0, 20, 0, "cafe"),
              block("b", 20, 0, 20, 45, "station"),
              block("c", 20, 45, 23, 59, "home")])
check("full account has no gaps", not r.gaps, f"gaps={[g.describe() for g in r.gaps]}")
check("full account is 'complete'", r.complete, f"coverage={r.coverage:.2f}")
check("coverage is ~100%", r.coverage > 0.99, f"{r.coverage:.3f}")

# A hole in the middle.
r = tl.build([block("a", 17, 0, 20, 0, "cafe"),
              block("c", 22, 0, 23, 59, "home")])
check("detects the 20:00-22:00 hole", len(r.gaps) == 1 and r.gaps[0].minutes == 120,
      str([g.describe() for g in r.gaps]))

# Two places at once.
r = tl.build([block("a", 20, 0, 22, 0, "cafe"),
              block("b", 21, 0, 22, 30, "bridge")])
check("detects being in two places at once", len(r.overlaps) == 1,
      str([o.describe() for o in r.overlaps]))

# Cafe -> bridge is 25 minutes on foot; only 5 claimed.
r = tl.build([block("a", 20, 0, 21, 0, "cafe"),
              block("b", 21, 5, 22, 0, "bridge")])
check("detects an impossible journey", len(r.impossible) == 1,
      str([m.describe() for m in r.impossible]))

# Same journey with enough time is fine.
r = tl.build([block("a", 20, 0, 21, 0, "cafe"),
              block("b", 21, 30, 22, 0, "bridge")])
check("allows the journey when time permits", not r.impossible)

# Never convict on invented bounds. "cafe until eight" (end only) then "walked
# home" (start only) are both one-bounded; the normaliser fills the gaps, which
# used to mint a phantom impossible move and a phantom clash from touching
# segments the learner narrated in good faith.
r = tl.build([Claim(id="a", turn_seq=1, text="cafe until eight",
                    end_min=20 * 60, location="cafe"),
              Claim(id="b", turn_seq=1, text="walked straight home",
                    start_min=20 * 60, location="home")])
check("no phantom impossible move from one-bounded narration", not r.impossible,
      str([m.describe() for m in r.impossible]))
check("no phantom overlap from one-bounded narration", not r.overlaps)
# A fully-stated genuine impossibility is still caught (neither bound inferred).
r = tl.build([block("a", 20, 0, 21, 0, "cafe"), block("b", 21, 5, 22, 0, "bridge")])
check("a fully-stated impossible journey is still caught", len(r.impossible) == 1)

# The gate that reverse chronology depends on.
r = tl.build([])
check("empty timeline is NOT complete", not r.complete)
r = tl.build([block("a", 17, 0, 18, 0, "cafe")])
check("one thin block is NOT complete", not r.complete, f"coverage={r.coverage:.2f}")

# Superseded claims drop out.
old = block("old", 17, 0, 20, 0, "cafe")
old.superseded_by = "new"
r = tl.build([old, block("new", 17, 0, 21, 0, "cafe")])
check("superseded claims are excluded", len(r.blocks) == 1 and r.blocks[0].id == "new")

# People speak in points, not intervals. Requiring both bounds discarded every
# real claim and left the timeline permanently empty.
half_open = [
    Claim(id="1", turn_seq=1, text="at the cafe until eight", end_min=1200, location="cafe"),
    Claim(id="2", turn_seq=1, text="walked straight home", start_min=1200, location="home"),
    Claim(id="3", turn_seq=2, text="home about half eight", start_min=1230, location="home"),
]
check("claims with only one bound are unusable raw",
      sum(1 for c in half_open if c.has_window) == 0)
norm = tl.normalised(half_open)
check("normalisation recovers them", len(norm) == 3, f"got {len(norm)}")
check("'until eight' gets a start from the window",
      norm[0].start_min == tl.WINDOW_START_MIN and norm[0].end_min == 1200)
check("'walked home' gets an end from the next claim", norm[1].end_min == 1230)
check("the last claim runs to the end of the window",
      norm[-1].end_min == tl.WINDOW_END_MIN)
r = tl.build(half_open)
check("a half-open account still yields a usable timeline", r.complete,
      f"coverage={r.coverage:.2f}")
check("invented bounds are marked as inferred", all(c.inferred for c in norm),
      "an inferred span may measure coverage but must not convict anyone")

stated = tl.normalised([block("s", 17, 0, 20, 0, "cafe")])
check("a fully stated window is NOT marked inferred", not stated[0].inferred)


print("\nSTATEMENT ANALYSIS  (language must never raise pressure)")

a = analyse("At the cafe.", responsive=True)
check("short BUT responsive is not evasive", not a.evasive, f"words={a.words}")

a = analyse("Sorry, I don't understand.", responsive=False)
check("struggling learner is not evasive", not a.evasive and a.struggling)

a = analyse("How do you say... the place with the coffee?", responsive=False)
check("reaching for a word is not evasive", not a.evasive and a.struggling)

a = analyse("Maybe.", responsive=False)
check("very short + hedged reads as struggling", not a.evasive and a.struggling)

a = analyse("I'm not answering that.", responsive=False)
check("explicit refusal IS evasive", a.evasive and a.refusal)

a = analyse("Anyway, the weather that week was unusual for the season.", responsive=False)
check("fluent deflection IS evasive", a.evasive, "long, fluent, not addressing the question")

a = analyse("I walked home.", responsive=True)
check("responsive answer is never evasive regardless of length", not a.evasive)

# Hedging and self-correction are CBCA truthfulness markers, not suspicion.
plain = analyse("I went home.", responsive=True)
rich = analyse("I left about eight, no wait, half eight. It was cold and the "
               "bridge was noisy. I think I got home around nine.", responsive=True)
check("hedges/corrections counted as truthful detail", rich.hedges > 0 and rich.corrections > 0)
check("richer account scores higher", rich.richness > plain.richness,
      f"{rich.richness} vs {plain.richness}")
check("richness never negative for hedging", analyse("Maybe about nine, I think.").richness > 0)


print("\nTACTIC GATING")

from engine import director as dr                       # noqa: E402
from engine import tactics as tac                       # noqa: E402
from engine.analysis import analyse as _an              # noqa: E402
from engine.state import (ChenStance, Contradiction,    # noqa: E402
                          InterviewState, Outcome, Stage)
from engine import density                             # noqa: E402
from scenario import briefs as briefs_mod               # noqa: E402
from scenario import case                               # noqa: E402
import prompts                                          # noqa: E402


def ctx_with(stage, claims=(), **kw):
    st = InterviewState(stage=stage.value)
    st.claims = list(claims)
    for k, v in kw.items():
        setattr(st, k, v)
    return dr.build_context(st, None), st


thin, _ = ctx_with(Stage.PROBE, [block("a", 17, 0, 18, 0, "cafe")])
ids = {t.id for t in tac.available(thin, "Reynolds")}
check("reverse chronology BLOCKED before a timeline exists", "reverse_chronology" not in ids)
check("unanticipated question BLOCKED before a timeline exists", "unanticipated_question" not in ids)

full_blocks = [block("a", 17, 0, 20, 0, "cafe"),
               block("b", 20, 0, 20, 45, "station"),
               block("c", 20, 45, 23, 59, "home")]
bare, _ = ctx_with(Stage.PROBE, full_blocks)
ids = {t.id for t in tac.available(bare, "Reynolds")}
# The whole point of the density gate: covering the evening is not the same as
# having said anything about it, and reversing a row of bare assertions proves
# nothing about anyone.
check("reverse chronology STILL BLOCKED while the account is bare",
      "reverse_chronology" not in ids,
      "three assertions with nobody in them is not an account worth reversing")
check("directed probing offered instead", "press_thin_detail" in ids, str(sorted(ids)))

full_rich = [probed("a", 17, 0, 20, 0, "cafe", "the cafe"),
             probed("b", 20, 0, 20, 45, "station", "the cafe", seq=2),
             probed("c", 20, 45, 22, 30, "home", "getting home", seq=3),
             probed("d", 22, 30, 23, 59, "home", "getting home", seq=4)]
ready, _ = ctx_with(Stage.PROBE, full_rich)
ids = {t.id for t in tac.available(ready, "Reynolds")}
check("reverse chronology UNLOCKED once the account has substance",
      "reverse_chronology" in ids, str(sorted(ids)))
check("directed probing stands down once nothing is thin",
      "press_thin_detail" not in ids)

# Stage gating.
engage, _ = ctx_with(Stage.ENGAGE, full_blocks)
ids = {t.id for t in tac.available(engage, "Reynolds")}
check("challenge tactics BLOCKED during Engage", "challenge_contradiction" not in ids
      and "sue_disclose" not in ids)

# Cooldowns.
cooled, st = ctx_with(Stage.PROBE, full_blocks)
st.cooldowns["reverse_chronology"] = 3
cooled = dr.build_context(st, None)
check("cooldown blocks a tactic", "reverse_chronology" not in
      {t.id for t in tac.available(cooled, "Reynolds")})

# Ownership.
ready, _ = ctx_with(Stage.CHALLENGE, full_blocks)
check("minimisation is Chen's only", "minimisation" not in
      {t.id for t in tac.available(ready, "Reynolds")})


print("\nTHE ASIDE  (guards)")

c, st = ctx_with(Stage.PROBE, full_blocks)
st.contradictions.append(Contradiction(id="x", kind="self", turn_seq=1, detail="d"))
c = dr.build_context(st, None)
check("aside available when there is something to confer about",
      "detective_aside" in {t.id for t in tac.available(c, "Reynolds")})

st.asides_this_stage = 2
c = dr.build_context(st, None)
check("aside capped per stage", "detective_aside" not in
      {t.id for t in tac.available(c, "Reynolds")})

st.asides_this_stage = 0
c = dr.build_context(st, None, _an("Sorry, I don't understand.", responsive=False))
check("aside suppressed while the learner is struggling",
      "detective_aside" not in {t.id for t in tac.available(c, "Reynolds")},
      "overheard dialogue is harder listening - must not pile on")
check("rapport repair offered instead",
      "rapport_repair" in {t.id for t in tac.available(c, "Chen")})


print("\nCHEN'S ARC  (the sting must be earned)")

st = InterviewState(stage=Stage.CHALLENGE.value, turn=10, pressure=0.9)
for _ in range(10):
    dr.update_chen(st, [], False)
check("stance cannot reach sting by pressure alone",
      st.chen_stance != ChenStance.STING.value, f"got {st.chen_stance}")
check("stance does climb the arc under pressure",
      st.chen_stance == ChenStance.MINIMISING.value, f"got {st.chen_stance}")

st2 = InterviewState(stage=Stage.CHALLENGE.value, turn=10, pressure=0.5)
fired = dr.update_chen(st2, [Contradiction(id="c", kind="self", turn_seq=3,
                                           detail="d", was_vouched=False)], False)
check("ordinary contradiction does NOT spring the trap", not fired
      and st2.chen_stance != ChenStance.STING.value)

st3 = InterviewState(stage=Stage.CHALLENGE.value, turn=10, pressure=0.5)
fired = dr.update_chen(st3, [Contradiction(id="c", kind="self", turn_seq=3,
                                           detail="d", was_vouched=True)], False)
check("contradicting a claim CHEN vouched for springs the trap",
      fired and st3.chen_stance == ChenStance.STING.value)

st3.pressure = 0.1
dr.update_chen(st3, [], False)
check("once stung, she does not go back to being nice",
      st3.chen_stance == ChenStance.STING.value)


print("\nPRESSURE  (language must never cost them)")

st = InterviewState()
rep = tl.build([])
before = st.pressure
dr.update_pressure(st, [], _an("At the cafe.", responsive=True), rep)
check("short but responsive does NOT raise pressure", st.pressure <= before)

st = InterviewState()
dr.update_pressure(st, [], _an("Sorry, how do you say it?", responsive=False), rep)
check("struggling for a word does NOT raise pressure", st.pressure == 0.0,
      f"pressure={st.pressure}")

st = InterviewState()
dr.update_pressure(st, [], _an("I'm not answering that.", responsive=False), rep)
check("refusing to answer DOES raise pressure", st.pressure > 0)

st = InterviewState()
dr.update_pressure(st, [Contradiction(id="e", kind="evidence", turn_seq=1, detail="d")],
                   _an("I was home.", responsive=True), rep)
check("evidence contradiction raises pressure most", st.pressure >= 0.12)

# A breach is the learner's own admission, so unlike everything else the engine
# knows, the detectives can hear it. It costs - but modestly, because conceding
# something should change the room rather than end the interview on the spot.
st = InterviewState()
dr.update_pressure(st, [Contradiction(id="b", kind="breach", turn_seq=1, detail="d")],
                   _an("I was down by the canal, yes.", responsive=True), rep)
check("conceding the concealed fact raises pressure", st.pressure > 0)
check("but conceding it does not slam pressure to the ceiling", st.pressure <= 0.15,
      f"pressure={st.pressure}")

# A single bad turn must not end the interview outright.
st = InterviewState()
many = [Contradiction(id=f"e{i}", kind="evidence", turn_seq=1, detail="d")
        for i in range(6)]
dr.update_pressure(st, many, _an("I'm not answering.", responsive=False), rep)
check("pressure gain is capped per turn", st.pressure <= 0.25, f"{st.pressure}")

# Concealing successfully and never being caught should be a win. Everyone is
# concealing now, so if this did not walk them out, nobody would ever walk.
st = InterviewState(stage=Stage.CLOSURE.value, pressure=0.1)
check("holding the pair together the whole way -> released",
      dr.decide_outcome(st) == Outcome.RELEASED.value,
      "they beat the interview; the engine knowing they concealed is not evidence")

# Evidence only counts once it has actually been put to them.
st = InterviewState(stage=Stage.CLOSURE.value, pressure=0.8)
st.contradictions.append(Contradiction(id="e", kind="evidence", turn_seq=1,
                                       detail="d", raised=False))
check("unput evidence does not detain them",
      dr.decide_outcome(st) != Outcome.DETAINED.value)


print("\nSPEAKER SPLIT  (triggers, not chance)")

st = InterviewState(stage=Stage.PROBE.value)
st.claims = list(full_blocks)
st.topics_covered = ["identity", "relationship"]
reasons = {}
for i in range(60):
    if i % 9 == 0:                       # evidence becomes due
        st.contradictions.append(Contradiction(id=f"x{i}", kind="evidence",
                                               turn_seq=i, detail="d",
                                               evidence_id="cell_tower"))
    if i % 13 == 0:                      # learner loses the thread
        st.nonresponsive_streak = 2
    c = dr.build_context(st, None)
    who, why = dr.select_speaker(c)
    reasons[why] = reasons.get(why, 0) + 1
    dr.note_speaker(st, who)
    st.nonresponsive_streak = 0
    st.turn += 1
    if i == 20:
        st.stage = Stage.CHALLENGE.value

share = st.lead_share()
triggered = sum(v for k, v in reasons.items() if k != "ratio")
check("lead share lands near the researched 75/25", 0.60 <= share <= 0.85, f"{share:.0%}")
check("hand-offs are driven by triggers, not the ratio fallback",
      triggered / sum(reasons.values()) >= 0.8, str(reasons))
check("more than one trigger type fires", len(set(reasons) - {"ratio"}) >= 3, str(reasons))

st = InterviewState(stage=Stage.PROBE.value, nonresponsive_streak=2)
c = dr.build_context(st, None)
who, why = dr.select_speaker(c)
check("a floundering learner is handed to Chen, not Reynolds",
      who == "Chen" and why == "rapport")


print("\nOUTCOMES")

st = InterviewState(stage=Stage.CLOSURE.value, pressure=0.05)
check("clean account -> released", dr.decide_outcome(st) == Outcome.RELEASED.value)

st = InterviewState(stage=Stage.CLOSURE.value, pressure=0.45)
st.contradictions.append(Contradiction(id="s", kind="self", turn_seq=1, detail="story moved"))
check("an account that moved -> under investigation",
      dr.decide_outcome(st) == Outcome.UNDER_INVESTIGATION.value)

# Would not talk, as against could not. analysis.evasive already excludes the
# learner who is struggling, so this can never catch low proficiency.
st = InterviewState(stage=Stage.CLOSURE.value, evasions=3)
check("stonewalling the whole interview -> under investigation",
      dr.decide_outcome(st) == Outcome.UNDER_INVESTIGATION.value,
      "otherwise saying nothing is the winning strategy")

# Detaining requires their own account to have given them away - either they
# conceded the concealed fact, or their story moved and evidence was put on it.
st = InterviewState(stage=Stage.CLOSURE.value, pressure=0.8)
st.contradictions += [
    Contradiction(id="e", kind="evidence", turn_seq=1, detail="d", raised=True),
    Contradiction(id="b", kind="breach", turn_seq=1, detail="placed themselves there"),
]
check("conceded it AND caught on evidence -> detained",
      dr.decide_outcome(st) == Outcome.DETAINED.value)

# A breach with nothing to corroborate it is an admission, not a case.
st = InterviewState(stage=Stage.CLOSURE.value, pressure=0.2)
st.contradictions.append(Contradiction(id="b", kind="breach", turn_seq=1, detail="d"))
check("conceding it alone -> under investigation, not detained",
      dr.decide_outcome(st) == Outcome.UNDER_INVESTIGATION.value)

st = InterviewState(stage=Stage.CLOSURE.value, pressure=0.8)
st.contradictions += [
    Contradiction(id="e", kind="evidence", turn_seq=1, detail="d", raised=True),
    Contradiction(id="s1", kind="self", turn_seq=1, detail="story moved"),
    Contradiction(id="s2", kind="self", turn_seq=2, detail="story moved again"),
]
check("story falling apart AND caught on evidence -> detained",
      dr.decide_outcome(st) == Outcome.DETAINED.value)

# The one that matters most, and the reason the evidence clash cannot decide
# this. Every clashable item sits at the bridge inside the span every brief tells
# them to conceal, so a cover story ALWAYS collides with the mast data. If that
# collision decided the ending, the only way to walk would be to give no account
# of that hour - and saying as little as possible would be the winning strategy.
st = InterviewState(stage=Stage.CLOSURE.value, pressure=0.95)
st.contradictions.append(Contradiction(id="e", kind="evidence", turn_seq=1,
                                       detail="a witness saw someone matching your description",
                                       raised=True))
check("a consistent account walks even when the evidence looks terrible",
      dr.decide_outcome(st) == Outcome.RELEASED.value,
      "being disbelieved is not being caught - and a collision they could not "
      "have avoided must not be what decides it")

# Holding the story together is what wins; letting it move is what loses.
st = InterviewState(stage=Stage.CLOSURE.value, pressure=0.95)
st.contradictions += [
    Contradiction(id="e", kind="evidence", turn_seq=1, detail="d", raised=True),
    Contradiction(id="s1", kind="self", turn_seq=2, detail="moved"),
    Contradiction(id="s2", kind="self", turn_seq=3, detail="moved again"),
]
check("the same evidence DOES bite once their story has moved twice",
      dr.decide_outcome(st) == Outcome.DETAINED.value)

# Exculpation is the counterweight the design promises. A genuinely strong,
# cooperative account (rich detail, and often having caught the false-premise
# probe) is forgiven its single lightest slip and walks - which is the only thing
# that gives catching the probe any effect on the ending.
st = InterviewState(stage=Stage.CLOSURE.value, exculpation=dr._EXCULPATION_CLEARS)
st.contradictions.append(Contradiction(id="s", kind="self", turn_seq=1, detail="one slip"))
check("a strong account is forgiven a single wobble -> released",
      dr.decide_outcome(st) == Outcome.RELEASED.value)

# The same wobble WITHOUT a strong account behind it lands where it always did.
st = InterviewState(stage=Stage.CLOSURE.value, exculpation=0.2)
st.contradictions.append(Contradiction(id="s", kind="self", turn_seq=1, detail="one slip"))
check("a wobble with a weak account still -> under investigation",
      dr.decide_outcome(st) == Outcome.UNDER_INVESTIGATION.value)

# It is a counterweight, not an eraser: it never lifts a heavier reading.
st = InterviewState(stage=Stage.CLOSURE.value, exculpation=1.0)
st.contradictions += [
    Contradiction(id="s1", kind="self", turn_seq=1, detail="moved"),
    Contradiction(id="s2", kind="self", turn_seq=2, detail="moved again"),
]
check("even a strong account is not forgiven a story that moved twice",
      dr.decide_outcome(st) == Outcome.UNDER_INVESTIGATION.value)

st = InterviewState(stage=Stage.CLOSURE.value, exculpation=1.0)
st.contradictions += [
    Contradiction(id="e", kind="evidence", turn_seq=1, detail="d", raised=True),
    Contradiction(id="s", kind="self", turn_seq=2, detail="moved"),
]
check("a strong account does not clear a wobble evidence was put on",
      dr.decide_outcome(st) == Outcome.UNDER_INVESTIGATION.value)

st = InterviewState(stage=Stage.CLOSURE.value, exculpation=1.0)
st.contradictions.append(Contradiction(id="b", kind="breach", turn_seq=1, detail="conceded"))
check("nor a concession, however strong the rest of the account",
      dr.decide_outcome(st) == Outcome.UNDER_INVESTIGATION.value)

st = InterviewState(stage=Stage.PROBE.value, pressure=0.9)
check("no outcome before closure", dr.decide_outcome(st) is None)


print("\nEVIDENCE FRAMING MATRIX")

# Escalation is driven by the level disclosed, and crucially works even once the
# item is RAISED - the production flow marks it raised on the first putting, and
# the old code retired any raised item so the matrix never escalated past vague.
st = InterviewState()
st.contradictions.append(Contradiction(id="c", kind="evidence", turn_seq=1,
                                       detail="d", evidence_id="cell_tower", raised=True))
check("evidence is first put vaguely", dr.next_disclosure(st) == ("cell_tower", "vague"))
st.disclosed["cell_tower"] = "vague"
check("then moderately - even though it is already raised",
      dr.next_disclosure(st) == ("cell_tower", "moderate"),
      "the matrix must escalate a raised item, not retire it")
st.disclosed["cell_tower"] = "moderate"
check("then precisely", dr.next_disclosure(st) == ("cell_tower", "precise"))
st.disclosed["cell_tower"] = "precise"
check("and once precise, nothing more to add", dr.next_disclosure(st) is None)

# sue_disclose stays AVAILABLE until the item is fully escalated.
c, _st = ctx_with(Stage.CHALLENGE, full_rich)
_st.contradictions.append(Contradiction(id="e", kind="evidence", turn_seq=1, detail="d",
                                         evidence_id="cell_tower", raised=True))
_st.disclosed["cell_tower"] = "vague"
c = dr.build_context(_st, None)
check("sue_disclose is still offered while escalation remains",
      "sue_disclose" in {t.id for t in tac.available(c, "Reynolds")})
_st.disclosed["cell_tower"] = "precise"
c = dr.build_context(_st, None)
check("and withdrawn once every item is precise",
      "sue_disclose" not in {t.id for t in tac.available(c, "Reynolds")})

# Weakest-first order across several minted items.
st = InterviewState()
for eid in ("cell_tower", "witness_sighting"):     # strong, then weaker
    st.contradictions.append(Contradiction(id=eid, kind="evidence", turn_seq=1,
                                            detail="d", evidence_id=eid))
check("disclosure works up from the weaker item first",
      dr.next_disclosure(st)[0] == "witness_sighting",
      "witness_sighting precedes cell_tower in DISCLOSURE_ORDER")

# Content evidence that the mechanical clash can never surface is referenceable,
# so the concealing brief's "the calls are on record" can actually bite.
ref_ids = {ev.id for ev in case.referenceable_evidence()}
check("phone_records is referenceable evidence", "phone_records" in ref_ids,
      "a call has a time but no place, so evidence_for skips it")
block_text = prompts._evidence_block(
    InterviewState(stage=Stage.CHALLENGE.value), None)
check("and it reaches the prompt in the challenge stage",
      "rang you twice" in block_text or "call" in block_text.lower(), block_text[:200])


print("\nDETAIL DENSITY  (what makes probing directed)")

sparse = [Claim(id="1", turn_seq=1, text="I was at the cafe.",
                location="cafe", topic="the cafe")]
d = density.assess(sparse)["the cafe"]
check("a bare topic is thin", d.thin, f"score={d.score}")
check("and it names what is missing",
      any("nobody named" in m.lower() for m in d.missing()), str(d.missing()))
check("it asks for a time when none was given",
      any("clock time" in m for m in d.missing()), str(d.missing()))

d = density.assess(full_rich)["the cafe"]
check("a probed topic is not thin", not d.thin, f"score={d.score}")
check("sensory detail is counted from their own words", d.sensory > 0)

# Distinct, not tallied. Repeating one name in five claims is one person, and
# counting it five times would call an empty topic rich.
same = [probed(f"r{i}", 18, 0, 19, 0, "cafe", "the cafe", seq=i) for i in range(5)]
check("repeating one name is one person, not five",
      density.assess(same)["the cafe"].people == 1)

dropped = Claim(id="x", turn_seq=1, text="I was at the cafe.",
                location="cafe", topic="the cafe")
dropped.superseded_by = "y"
check("a claim they have since replaced is not detail their account carries",
      "the cafe" not in density.assess([dropped]))

check("a single middling topic is not yet a testable account",
      not density.testable(full_rich[:2]),
      f"score={density.assess(full_rich[:2])['the cafe'].score}")
check("two rich topics are", density.testable(full_rich))

# Topics are free-text labels the MODEL supplies. If it reuses one all
# interview, a hard topic-count gate would lock reverse chronology out of every
# run - the precise failure this layer exists to end.
one_big_topic = [probed(f"b{n}", 17 + n, 0, 18 + n, 0, "cafe", "the evening", seq=n)
                 for n in range(5)]
check("one substantial topic still counts, whatever the model labelled it",
      density.testable(one_big_topic),
      f"score={density.assess(one_big_topic)['the evening'].score}")
check("but a thin single topic never does",
      not density.testable(sparse))

# Probing and testing are separate questions. A freshly raised topic must not
# re-lock reverse chronology over an account already worth attacking.
mixed = list(full_rich) + [Claim(id="new", turn_seq=9, text="and a pub after",
                                 start_min=23 * 60, end_min=23 * 60 + 30,
                                 location="home", topic="the pub")]
check("a new thin topic still gets pressed",
      any(d.topic == "the pub" for d in density.thin_topics(mixed)))
check("but it does not re-lock an account already worth testing",
      density.testable(mixed),
      "a real interview raises topics constantly; one mention cannot undo the rest")

# "Some friends" is not somebody the police can go and find.
check("a real name counts", density.is_named("James") and density.is_named("Sam"))
check("a bare plural does not",
      not any(density.is_named(p) for p in
              ["friends", "some friends", "a few friends", "my mates", "the staff",
               "someone", "colleagues", "a friend"]),
      "this is the vagueness probing exists to go after")

vague_people = [Claim(id="v", turn_seq=1, text="I was with some friends",
                      start_min=18 * 60, end_min=19 * 60, location="cafe",
                      people=["some friends"], activity="drinking", topic="the pub")]
check("a topic whose only 'person' is 'some friends' is thin",
      density.assess(vague_people)["the pub"].thin,
      "it scored full marks for naming nobody before this")
check("a bare account is never testable however much time it covers",
      not density.testable(full_blocks))

# ── episodic vs procedural ───────────────────────────────────────────────────
# Habitual narration - keys on the table, shoes on the rack, the usual seat -
# is rehearsed by definition, so it comes back identical on a second telling and
# the retelling test can never find anything in it. Banking it as testable meant
# a beautifully told routine armed an attack that then had nothing to bite.
habitual = [probed(f"h{n}", 17 + n, 0, 18 + n, 0, "home", "the evening", seq=n)
            for n in range(5)]
for c in habitual:
    c.episodic = False
check("an account of what they ALWAYS do is not testable",
      not density.testable(habitual),
      "habit is consistent by nature, so a second telling cannot catch it out")
check("but that same detail still scores as rich language",
      not density.assess(habitual)["the evening"].thin,
      "declining to weaponise procedural detail is not the same as penalising it")

episodic_acct = [probed(f"e{n}", 17 + n, 0, 18 + n, 0, "home", "the evening", seq=n)
                 for n in range(5)]
check("the same account tagged as that NIGHT is testable",
      density.testable(episodic_acct))

check("a claim nobody tagged counts as episodic",
      Claim(id="u", turn_seq=1, text="x").episodic,
      "an untagged extraction must behave exactly as it did before the flag")

# The trap this could have re-opened. If a purely habitual account can never be
# testable, probing still has to be able to end - PROBE_PATIENCE is the escape,
# and narrating your own routine well must never become a punishment.
st = InterviewState(stage=Stage.PROBE.value, turn=dr.PROBE_PATIENCE)
st.claims = list(habitual)
dr.advance_stage(st, tl.build(habitual))
check("a purely habitual account still escapes probing on patience",
      Stage(st.stage) is Stage.CHALLENGE,
      "otherwise telling your routine well would trap you in PROBE forever")

# The lesson of `topic_complete`: it was added with no Field description and no
# mention in the extraction prompt, so the model never once set it and 8 of 13
# interviews ended with zero topics covered. An extraction field has to be
# documented in BOTH places or it silently never fires. This pins that for
# `episodic`, whose whole job depends on the model actually setting it.
import prompts as _prompts                              # noqa: E402
from agent import ClaimOut as _ClaimOut                 # noqa: E402

_sys = _prompts.build_system_prompt("Reynolds", InterviewState(), tl.build([]), [])
check("the episodic field is documented in the extraction prompt",
      "episodic" in _sys,
      "a field the prompt never mentions is a field the model never sets")
check("and it carries a description on the schema itself",
      bool(_ClaimOut.model_fields["episodic"].description))


print("\nEMPTY EVENING  (a soft hook, never a lie)")

alone = [Claim(id=f"a{n}", turn_seq=n, text="I watched TV on the sofa",
               start_min=(19 + n) * 60, end_min=(20 + n) * 60, location="home",
               topic="the evening") for n in range(3)]

check("an evening with nobody and no messages has no contact",
      not density.has_contact(alone))
check("naming a person is contact",
      density.has_contact([Claim(id="p", turn_seq=1, text="I was in", people=["Sam"])]))
check("a text or a call in the words is contact",
      density.has_contact([Claim(id="t", turn_seq=1, text="I texted my brother about nine")])
      and density.has_contact([Claim(id="c", turn_seq=1, text="I rang the takeaway")]))
# has_contact is a WIDER question than is_named: "some friends" is not a person the
# police can find (so it stays thin), but it does mean they were not home alone.
check("vague company still counts as contact, not an empty evening",
      density.has_contact([Claim(id="v", turn_seq=1, text="out", people=["some friends"])])
      and not density.is_named("some friends"))
sup = Claim(id="s", turn_seq=1, text="I called Mum")
sup.superseded_by = "x"
check("a retracted contact does not count", not density.has_contact([sup]))

# The comms regex must not read a boxing/bells "ring" or a clock "dial" as a phone
# call - a false positive there would offer the "those records exist" reminder with
# nothing on record. Real report verbs (rang/called/texted/dialled) still count.
for noise in ("I could hear the church bells ring", "we watched the boxing ring",
              "the clock dial said ten past"):
    check(f"no false phone contact in {noise!r}",
          not density.has_contact([Claim(id="n", turn_seq=1, text=noise)]))
for real in ("I rang my brother", "I called the takeaway", "I texted Sam",
             "I dialled her number"):
    check(f"a real call still reads as contact: {real!r}",
          density.has_contact([Claim(id="r", turn_seq=1, text=real)]))

# The hook is surfaced in the prompt only once there is an account to hang it on,
# and never when the account already has contact in it.
st_alone = InterviewState(); st_alone.claims = list(alone)
sys_alone = _prompts.build_system_prompt("Reynolds", st_alone, tl.build(alone), [])
check("the empty-evening hook is surfaced once an account exists",
      "NO CONTACT" in sys_alone)

social = [Claim(id=f"s{n}", turn_seq=n, text="we chatted on the sofa",
                start_min=(19 + n) * 60, end_min=(20 + n) * 60, location="home",
                people=["Sam"], topic="the evening") for n in range(3)]
st_social = InterviewState(); st_social.claims = list(social)
sys_social = _prompts.build_system_prompt("Reynolds", st_social, tl.build(social), [])
check("but not when the account already has contact",
      "NO CONTACT" not in sys_social)

sys_empty = _prompts.build_system_prompt("Reynolds", InterviewState(), tl.build([]), [])
check("and not before there is any account at all",
      "NO CONTACT" not in sys_empty)

# Once the absence has actually been put, the prompt stops raising it - in lockstep
# with the one-shot phone_absence_hook, so the model is not re-nudged every turn.
st_probed = InterviewState(phone_probed=True); st_probed.claims = list(alone)
sys_probed = _prompts.build_system_prompt("Reynolds", st_probed, tl.build(alone), [])
check("and not once the empty-evening hook has already been put",
      "NO CONTACT" not in sys_probed,
      "re-raising the absence every turn is the interview spinning")

# The invariants the note is adamant about: absence is never scored.
st = InterviewState(stage=Stage.CLOSURE.value, pressure=0.1); st.claims = list(alone)
check("an honest contactless evening can still walk",
      dr.decide_outcome(st) == Outcome.RELEASED.value,
      "\"I messaged nobody\" is a hook to press, not evidence of fabrication")
# Isolate the absence from ordinary gap pressure: a contactless but otherwise
# clean account - the whole window accounted for, no contradictions - draws no
# pressure from the emptiness, because contact is not an input to update_pressure
# at all. (An account that leaves time unaccounted is charged for the GAP, which
# is a separate, legitimate signal - not for having no contact.)
clean_alone = [Claim(id="ca", turn_seq=1,
                     text="I was home on my own all evening watching TV",
                     start_min=17 * 60, end_min=23 * 60 + 59, location="home",
                     topic="the evening")]
st = InterviewState(); before = st.pressure
dr.update_pressure(st, [], _an("I was home on my own, watched TV.", responsive=True),
                   tl.build(clean_alone))
check("an empty but otherwise clean evening raises no pressure",
      st.pressure <= before and not density.has_contact(clean_alone))


print("\nPHONE THREAD  (episodic, checkable ground)")

# mentioned_comms is NARROWER than has_contact: a call/text/message on the record,
# not merely company. "those records exist" only bites on something a phone logs.
check("a text or call on the record is comms",
      density.mentioned_comms([Claim(id="m", turn_seq=1, text="I texted my brother at nine")])
      and density.mentioned_comms([Claim(id="m2", turn_seq=1, text="I rang the takeaway")]))
check("but sitting with a friend is contact, not comms",
      density.has_contact([Claim(id="p", turn_seq=1, text="on the sofa", people=["Sam"])])
      and not density.mentioned_comms([Claim(id="p2", turn_seq=1, text="on the sofa",
                                             people=["Sam"])]))

# The absence hook: a real account with no contact in it, in PROBE, and only once.
ctx, _ = ctx_with(Stage.PROBE, full_blocks)
check("the empty-evening hook is offered on a contactless account",
      "phone_absence_hook" in {t.id for t in tac.available(ctx, "Reynolds")})

ctx, _ = ctx_with(Stage.PROBE, full_blocks, phone_probed=True)
check("but not once it has already been put",
      "phone_absence_hook" not in {t.id for t in tac.available(ctx, "Reynolds")},
      "pressing the same absence twice reads as the interview spinning")

social_blocks = list(full_blocks) + [block("s", 21, 0, 21, 5, "home", "I texted Sam", seq=4)]
ctx, _ = ctx_with(Stage.PROBE, social_blocks)
check("and not once the account HAS contact in it",
      "phone_absence_hook" not in {t.id for t in tac.available(ctx, "Reynolds")})

ctx, _ = ctx_with(Stage.PROBE, [])
check("nor before there is any account to hang it on",
      "phone_absence_hook" not in {t.id for t in tac.available(ctx, "Reynolds")})

# The verifiability reminder: needs a comms claim on the record; PROBE and CHALLENGE;
# once. It has real backing - phone_records is on file - so it is not a bluff.
comms = list(full_blocks) + [block("c", 21, 0, 21, 5, "home",
                                   "I called the takeaway about nine", seq=4)]
ctx, _ = ctx_with(Stage.CHALLENGE, comms)
check("the records reminder is offered once a call is on the record",
      "phone_verifiability" in {t.id for t in tac.available(ctx, "Reynolds")})
ctx, _ = ctx_with(Stage.PROBE, comms)
check("and in probe too, not only challenge",
      "phone_verifiability" in {t.id for t in tac.available(ctx, "Reynolds")})

company = list(full_blocks) + [Claim(id="w", turn_seq=4, text="I was with Sam",
                                     start_min=21 * 60, end_min=22 * 60, location="home",
                                     people=["Sam"])]
ctx, _ = ctx_with(Stage.CHALLENGE, company)
check("but not for company alone - a sofa chat is not a phone record",
      "phone_verifiability" not in {t.id for t in tac.available(ctx, "Reynolds")})

ctx, _ = ctx_with(Stage.CHALLENGE, comms, phone_reminder_spent=True)
check("and not once the reminder has been spent",
      "phone_verifiability" not in {t.id for t in tac.available(ctx, "Reynolds")})

# The one-shot flags are engine state, so they must survive a resume.
st = InterviewState(phone_probed=True, phone_reminder_spent=True)
rt = InterviewState.from_dict(st.to_dict())
check("the phone one-shot flags survive the JSON round-trip",
      rt.phone_probed and rt.phone_reminder_spent)
check("and they default off on a fresh state",
      not InterviewState().phone_probed and not InterviewState().phone_reminder_spent)

# Density must never be a stick. It says where to ask next, and nothing else.
st = InterviewState()
before = st.pressure
dr.update_pressure(st, [], _an("Yes.", responsive=True), tl.build(sparse))
check("a thin account does NOT raise pressure", st.pressure <= before,
      "a learner short of vocabulary is doing the thing the app exists to make them do")

# A standing timeline artifact is charged ONCE, not every turn it persists.
# cafe->bridge is 25 min on foot; 5 claimed -> a real impossible move.
imp = [block("a", 20, 0, 21, 0, "cafe"), block("b", 21, 5, 22, 0, "bridge")]
rep_imp = tl.build(imp)
check("the fixture really has an impossible move", bool(rep_imp.impossible))
st = InterviewState()
st.claims = list(imp)
dr.update_pressure(st, [], _an("I walked over.", responsive=True), rep_imp)
after_first = st.pressure
check("the impossible move charges pressure the first time", after_first > 0)
for _ in range(10):                          # ten more turns, same standing artifact
    dr.update_pressure(st, [], _an("Same as I said.", responsive=True), rep_imp)
check("but never again while it stands - no ratchet",
      st.pressure <= after_first,
      f"pressure {after_first:.2f} -> {st.pressure:.2f}; a stale artifact must not compound")

# The signature is stable across a resume (it is persisted, not recomputed).
round_tripped = InterviewState.from_dict(st.to_dict())
before_resume = round_tripped.pressure
dr.update_pressure(round_tripped, [], _an("Still the same.", responsive=True), rep_imp)
check("and the charge is not repeated after a resume",
      round_tripped.pressure <= before_resume)


print("\nPROBE PATIENCE  (probing ends on substance, not on a counter)")

st = InterviewState(stage=Stage.PROBE.value, turn=5)
st.claims = list(full_blocks)
st.topics_covered = ["identity", "the evening", "Emily"]
dr.advance_stage(st, tl.build(st.claims))
check("probing continues while the account is bare", st.stage == Stage.PROBE.value)

st.turn = dr.PROBE_PATIENCE
dr.advance_stage(st, tl.build(st.claims))
check("but a learner who cannot produce detail is moved on, not held there",
      st.stage == Stage.CHALLENGE.value,
      "holding them in probing would make low proficiency mean a longer interview")

st = InterviewState(stage=Stage.PROBE.value, turn=5)
st.claims = list(full_rich)
st.topics_covered = ["identity", "the evening", "Emily"]
dr.advance_stage(st, tl.build(st.claims))
check("a rich account reaches challenge without waiting",
      st.stage == Stage.CHALLENGE.value)

# The trap: a SPARSE account never reaches report.complete (needs 3 timed
# blocks), so the patience escape must NOT be gated behind it, and the interview
# must still be able to conclude.
sparse_pair = [Claim(id="s1", turn_seq=1, text="I was out", start_min=19 * 60, location="cafe"),
               Claim(id="s2", turn_seq=2, text="then home", start_min=21 * 60, location="home")]
st = InterviewState(stage=Stage.PROBE.value, turn=dr.PROBE_PATIENCE)
st.claims = list(sparse_pair)
check("the sparse account is genuinely not report.complete",
      not tl.build(st.claims).complete)
dr.advance_stage(st, tl.build(st.claims))
check("a sparse account still escapes Probe at the patience limit",
      st.stage == Stage.CHALLENGE.value,
      "report.complete needs 3 timed blocks a thin account never reaches")

# And it can actually END - drive a stuck-from-the-start run to the cap.
st = InterviewState(stage=Stage.PROBE.value, turn=1)
st.claims = list(sparse_pair)
reached = None
for t in range(1, dr.MAX_TURNS + 3):
    st.turn = t
    dr.advance_stage(st, tl.build(st.claims))
    if Stage(st.stage) is Stage.CLOSURE:
        reached = t
        break
check("a perpetually sparse account still reaches Closure by MAX_TURNS",
      reached is not None and reached <= dr.MAX_TURNS,
      f"reached closure at turn {reached}")

# The MAX_TURNS backstop closes even a run somehow still in an early stage.
st = InterviewState(stage=Stage.ENGAGE.value, turn=dr.MAX_TURNS)
dr.advance_stage(st, tl.build([]))
check("the backstop closes any stage stuck at the cap",
      st.stage == Stage.CLOSURE.value)


print("\nTHE CONCEALMENT PAIR")

for b in briefs_mod.BRIEFS.values():
    check(f"{b.id}: the denial is checkable (place and window)",
          bool(b.denial.location and b.denial.window_min))
    dw, sw = b.denial.window_min, b.substitution.window_min
    check(f"{b.id}: the pair is entangled - both halves share a span",
          bool(sw and dw[0] < sw[1] and sw[0] < dw[1]),
          f"denial={dw} substitution={sw} - unrelated secrets do not compound")
    check(f"{b.id}: two things to conceal, no more", len(b.concealments) == 2)
    # The panel heading already says "Do not admit". A denial phrased as a
    # negation renders as a double negative on the briefing screen - which is
    # exactly how false_alibi first shipped, reading as a flat contradiction of
    # the substitution sitting underneath it.
    check(f"{b.id}: the denial states what happened, not what did not",
          " not " not in f" {b.denial.text.lower()} ",
          f"'{b.denial.text}' - the heading supplies the negation; the text must not")

canal = briefs_mod.BRIEFS["canal_walk"]          # bridge, 21:15-22:20


def ingested(claims, brief=canal):
    st = InterviewState()
    return st, dr.ingest(st, dr.Extraction(claims=claims), brief, 1)


_, found = ingested([{"text": "I walked along the canal about half nine",
                      "start_min": 21 * 60 + 30, "location": "bridge"}])
check("placing themselves at the concealed spot IS a breach",
      any(c.kind == "breach" for c in found))

_, found = ingested([{"text": "I walked the canal at lunchtime",
                      "start_min": 13 * 60, "location": "bridge"}])
check("the right place at the wrong time is not a breach",
      not any(c.kind == "breach" for c in found))

_, found = ingested([{"text": "I was at home all evening",
                      "start_min": 21 * 60 + 30, "location": "home"}])
check("the wrong place in the window is not a breach",
      not any(c.kind == "breach" for c in found))

# The rule the whole engine is built on: no confession extracted from the
# engine's own arithmetic.
_, found = ingested([{"text": "I know the canal well", "location": "bridge"}])
check("naming the place with no time stated is NOT a breach",
      not any(c.kind == "breach" for c in found),
      "the timeline would happily invent a bound; an invented bound is not a confession")

st, found = ingested([{"text": "I was by the bridge", "start_min": 21 * 60 + 20,
                       "location": "bridge"}])
dr.ingest(st, dr.Extraction(claims=[{"text": "yes, the bridge, about ten to ten",
                                     "start_min": 21 * 60 + 50, "location": "bridge"}]),
          canal, 2)
check("conceding it twice is still one breach",
      len([c for c in st.contradictions if c.kind == "breach"]) == 1)

# Density is measured per topic, so the tag has to survive ingest - otherwise
# every claim lands in one bucket and no topic ever reads as thin.
st = InterviewState()
dr.ingest(st, dr.Extraction(claims=[{"text": "the cafe was busy", "location": "cafe"}],
                            topic="the cafe"), canal, 1)
check("the live topic is carried onto the claim", st.claims[0].topic == "the cafe")

st = InterviewState(current_topic="the walk home")
dr.ingest(st, dr.Extraction(claims=[{"text": "it was raining", "location": "home"}]),
          canal, 1)
check("a claim with no topic named falls to the topic already running",
      st.claims[0].topic == "the walk home")

check("a retired brief id deals a pair rather than stranding the interview",
      briefs_mod.get("innocent_missed_calls") is not None)
check("and the same retired id always deals the same pair",
      briefs_mod.get("innocent_missed_calls").id
      == briefs_mod.get("innocent_missed_calls").id)


print("\nSAME PLACE, DIFFERENT TIME  (how an account really moves)")


def said(st, turn, text, start=None, end=None, location=None, place=None):
    st.turn = turn
    return dr.ingest(st, dr.Extraction(claims=[{
        "text": text, "start_min": start, "end_min": end,
        "location": location, "place": place}], topic="the evening"),
        None, turn)


# Taken from a real interview. All three were about the cafe, so the detector -
# which only compared claims naming DIFFERENT places - passed over every one.
st = InterviewState()
said(st, 3, "went to a cafe from about seven till eight", 19 * 60, 20 * 60, "cafe")
found = said(st, 4, "I got there about 6 and left about 7.30", 18 * 60, 19 * 60 + 30, "cafe")
check("the same place at a different time IS a contradiction now",
      any(c.kind == "self" for c in found),
      "arriving at seven and at six, in one account, went unremarked")

st = InterviewState()
said(st, 3, "left the cafe about eight", None, 20 * 60, "cafe")
found = said(st, 4, "left the cafe about ten past eight", None, 20 * 60 + 10, "cafe")
check("but refining a time is not", not found,
      "'about eight' becoming 'ten past' is a learner being careful")

st = InterviewState()
said(st, 3, "I was at the cafe", None, None, "cafe")
found = said(st, 4, "the cafe, until about eight", None, 20 * 60, "cafe")
check("supplying a bound they had not given is not a change", not found)

# Most of an evening happens somewhere the four case locations cannot express.
st = InterviewState()
said(st, 3, "dinner at the Indian place from half eight", 20 * 60 + 30, 22 * 60,
     None, "the indian restaurant")
found = said(st, 4, "we got to the Indian place about half nine", 21 * 60 + 30, 22 * 60,
             None, "the indian restaurant")
check("a place outside the case vocabulary is compared too",
      any(c.kind == "self" for c in found),
      "24 of 30 claims in the real run had no case location and were invisible")

st = InterviewState()
said(st, 3, "a drink at the pub", 17 * 60, 18 * 60, None, "the pub")
found = said(st, 4, "dinner at the Indian place", 17 * 60, 18 * 60, None,
             "the indian restaurant")
check("two different named places at once is still caught",
      any(c.kind == "self" for c in found))

st = InterviewState()
said(st, 3, "I was somewhere", 17 * 60, 18 * 60)
found = said(st, 4, "I was somewhere else", 17 * 60, 18 * 60)
check("claims naming nowhere at all are not guessed about", not found,
      "with no place on either, there is nothing to say they conflict")

# The one that nearly detained three honest learners. People narrate a single
# stay in consecutive pieces, and end-to-end segments are not two arrivals.
st = InterviewState()
said(st, 3, "I was at the cafe from five", 17 * 60, 19 * 60, "cafe")
found = said(st, 4, "between seven and eight I was reading there", 19 * 60, 20 * 60, "cafe")
check("one stay described in consecutive parts is NOT a contradiction", not found,
      "'from five' then 'seven till eight' is segmentation, not arriving twice")

st = InterviewState()
said(st, 3, "the pub, five till six", 17 * 60, 18 * 60, None, "the pub")
found = said(st, 4, "then the pub again later, eight till nine", 20 * 60, 21 * 60,
             None, "the pub")
check("going back to the same place later is not a contradiction either",
      not found, "two separate visits do not overlap, so they are not one episode")


print("\nPLACE MATCHING  (re-mentions of one place are one place)")

check("'Pig & Whistle' matches 'the Pig and Whistle pub in Angel Islington'",
      dr.same_place("pig & whistle", "the pig and whistle pub in angel islington"))
check("'the cafe' matches 'a cafe somewhere on the High Street'",
      dr.same_place("the cafe", "a cafe somewhere on the high street"))
check("case location 'cafe' matches 'the Blue Door Cafe'",
      dr.same_place("cafe", "the blue door cafe"))
check("'the tube station in Highbury' matches 'near the tube station'",
      dr.same_place("the tube station in highbury", "near the tube station"))
check("the pub does not match the cafe",
      not dr.same_place("the pig and whistle", "the blue door cafe"))
check("noise words alone never match",
      not dr.same_place("the", "somewhere near"))


print("\nSELF-CONTRADICTION HYGIENE  (from a real transcript)")

# The t17 disaster: one vague re-mention of the pub - start bound only - minted
# NINE contradictions, colliding with everything from finishing work to leaving
# the restaurant at ten, because its missing end was normalised across the whole
# evening and 'Pig & Whistle' compared unequal to its own earlier mentions.
st = InterviewState()
said(st, 3, "finished work about five", 17 * 60, 17 * 60, None, "work")
said(st, 3, "drink with colleagues at the Pig and Whistle", 17 * 60, 18 * 60 + 30,
     None, "the Pig and Whistle pub in Angel Islington")
said(st, 4, "I arrived at the cafe at 6.45", 18 * 60 + 45, None, "cafe", "the cafe")
said(st, 4, "left the cafe about quarter to eight", None, 19 * 60 + 45, "cafe", "the cafe")
said(st, 5, "dinner just after eight", 20 * 60 + 5, None, None, "an Indian restaurant")
said(st, 5, "left there about 10", 22 * 60, None, None, "the restaurant")
found = said(st, 6, "we went to the pub, Pig & Whistle", 17 * 60, None,
             None, "Pig & Whistle")
check("a vague re-mention of the pub mints NOTHING",
      not [c for c in found if c.kind == "self"],
      str([c.detail[:70] for c in found]))

# One answer moves the story once. Even a turn that genuinely conflicts with
# several prior claims is one movement, not a pile-on.
st = InterviewState()
said(st, 3, "at the cafe seven till eight", 19 * 60, 20 * 60, "cafe", "the cafe")
said(st, 3, "still at the cafe until nine", 20 * 60, 21 * 60, "cafe", "the cafe")
found = said(st, 4, "I was at the pub all evening", 19 * 60, 22 * 60, None, "the pub")
check("even a turn that breaks several claims mints at most ONE",
      len([c for c in found if c.kind == "self"]) == 1,
      str([c.detail[:60] for c in found]))

# Sequential narration with single bounds - the shape nearly every real answer
# has - is not omnipresence.
st = InterviewState()
said(st, 3, "I was at the cafe until eight", None, 20 * 60, "cafe", "the cafe")
found = said(st, 4, "then dinner in Highbury from about half eight",
             20 * 60 + 30, None, None, "a restaurant in Highbury")
check("sequential one-bounded claims do not collide",
      not [c for c in found if c.kind == "self"],
      "the missing bounds are the timeline's invention, not their statement")

# Fully stated, genuinely impossible - still caught.
st = InterviewState()
said(st, 3, "at the cafe from seven to eight", 19 * 60, 20 * 60, "cafe", "the cafe")
found = said(st, 4, "at the pub from seven to eight", 19 * 60, 20 * 60, None, "the pub")
check("a genuine two-places claim, fully stated, is still caught",
      any(c.kind == "self" for c in found))

# Evidence never fires on invented bounds either. A single stated time is a
# POINT, not a span reaching the window edge: "got to the pub about nine"
# commits them to nine, not to the whole evening, so it cannot walk into
# evidence covering a later hour.
st = InterviewState()
found = said(st, 3, "got to the pub about nine", 21 * 60, None, None, "the pub")
check("a half-open claim mints no evidence contradiction",
      not [c for c in found if c.kind == "evidence"],
      "the founding rule: never convict on a bound the learner did not state")
# But a fully committed alibi that overlaps the mast still collides - the
# jeopardy the ending is designed around.
st = InterviewState()
found = said(st, 3, "I was home from nine until eleven", 21 * 60, 23 * 60, "home", "home")
check("a stated span overlapping the mast still clashes",
      any(c.kind == "evidence" for c in found),
      "SUE fires on a committed fact; this one is fully committed")

# A departure time is when a stay ENDED. Compared as a start, "arrived at 6.30"
# then "left about 7.45" reads as a 75-minute lie about arriving - which is how
# the interview got hung up on one vague half-hour for four turns.
st = InterviewState()
said(st, 3, "I arrived at the cafe at 6.30", 18 * 60 + 30, None, "cafe", "the cafe")
found = said(st, 4, "I left the cafe about quarter to eight", 19 * 60 + 45, None,
             "cafe", "the cafe")
check("arriving and then leaving the same place is a stay, not a contradiction",
      not [c for c in found if c.kind == "self"],
      str([c.detail[:70] for c in found]))
check("and the departure landed as the stay's end",
      st.claims[-1].end_min == 19 * 60 + 45 and st.claims[-1].start_min is None)

st = InterviewState()
said(st, 3, "I left the cafe about eight", 20 * 60, None, "cafe", "the cafe")
found = said(st, 4, "I left the cafe about seven", 19 * 60, None, "cafe", "the cafe")
check("two different LEAVING times for one place still collide",
      any(c.kind == "self" and "leaving" in c.detail for c in found),
      str([c.detail[:70] for c in found]))

# "Left at 7:45 because I was meeting them at eight" is not fifteen minutes of
# being at the cafe - a departure sentence asserts no span of presence at all,
# and treating its two times as one manufactured overlaps with wherever they
# actually were during those minutes.
st = InterviewState()
said(st, 3, "I walked up the High Street window shopping", 19 * 60 + 45, 20 * 60,
     None, "the High Street")
found = said(st, 4, "I left the cafe about 7.45 because I was meeting friends at eight",
             19 * 60 + 45, 20 * 60, "cafe", "the cafe")
check("a departure with a second time in it does not become a span of presence",
      not [c for c in found if c.kind == "self"],
      str([c.detail[:70] for c in found]))
check("its departure time still lands as the stay's end",
      st.claims[-1].end_min == 19 * 60 + 45 and st.claims[-1].start_min is None)


print("\nRE-TELLING MODE  (the second telling is the test)")


def first_telling():
    """An account given once, ready to be asked for again."""
    st = InterviewState(turn=8)
    dr.ingest(st, dr.Extraction(claims=[
        {"text": "I was at the cafe with Sam", "start_min": 18 * 60, "end_min": 20 * 60,
         "location": "cafe", "activity": "eating", "people": ["Sam"]},
        {"text": "then I walked home", "start_min": 20 * 60, "end_min": 21 * 60,
         "location": "home", "activity": "walking", "people": []},
    ], topic="the evening"), None, 8)
    return st


def retell(st, claims, turn=None):
    """Feed a second telling in, with the window already armed."""
    st.turn = turn or (st.retelling_from_turn + 1)
    return dr.ingest(st, dr.Extraction(claims=claims, topic="the evening"),
                     None, st.turn)


st = first_telling()
check("asking for it again is not itself a re-telling",
      not st.is_retelling(8), "the answer does not arrive until the turn after")
dr.arm_retelling(st, "reverse_chronology")
check("reverse chronology arms the window", st.is_retelling(9))
check("and the window lapses", not st.is_retelling(9 + dr.RETELLING_TURNS))

st2 = first_telling()
dr.arm_retelling(st2, "funnel_probe")
check("an ordinary probe does NOT arm it", not st2.is_retelling(9))

# The mechanic itself: same ground, different answer.
st = first_telling(); dr.arm_retelling(st, "reverse_chronology")
found = retell(st, [{"text": "I was at the bridge then", "start_min": 18 * 60,
                     "end_min": 20 * 60, "location": "bridge", "activity": "eating"}])
check("a place that moved between tellings is caught",
      any(c.kind == "retelling" for c in found),
      str([(c.kind, c.detail) for c in found]))

st = first_telling(); dr.arm_retelling(st, "reverse_chronology")
found = retell(st, [{"text": "I was at the cafe with Alex", "start_min": 18 * 60,
                     "end_min": 20 * 60, "location": "cafe", "people": ["Alex"]}])
check("a name swapped for another is caught",
      any(c.kind == "retelling" for c in found), str([c.detail for c in found]))

st = first_telling(); dr.arm_retelling(st, "reverse_chronology")
found = retell(st, [{"text": "the cafe, about seven", "start_min": 19 * 60,
                     "end_min": 21 * 60, "location": "cafe"}])
check("an episode that slid an hour is caught",
      any(c.kind == "retelling" for c in found), str([c.detail for c in found]))

# A free-text place (not one of the four case locations, so location=None) that
# is swapped for another between tellings is the substitution this test exists to
# catch - and the old location-only check, with None on both sides, passed over
# every one of them. Most places people name are not case locations.
st = InterviewState(turn=8)
dr.ingest(st, dr.Extraction(claims=[
    {"text": "I was at the pub with Sam", "start_min": 18 * 60, "end_min": 20 * 60,
     "place": "the pub", "people": ["Sam"]}], topic="the evening"),
    None, 8)
dr.arm_retelling(st, "reverse_chronology")
found = retell(st, [{"text": "I was at the restaurant then", "start_min": 18 * 60,
                     "end_min": 20 * 60, "place": "the restaurant"}])
check("a free-text place that moved between tellings is caught",
      any(c.kind == "retelling" for c in found),
      str([(c.kind, c.detail) for c in found]))

# ── the guards. Each of these would punish an honest learner. ────────────────

st = first_telling(); dr.arm_retelling(st, "reverse_chronology")
found = retell(st, [{"text": "I was at the cafe with Sam", "start_min": 18 * 60,
                     "end_min": 20 * 60, "location": "cafe", "activity": "eating",
                     "people": ["Sam"]}])
check("an account that holds costs nothing", not found, str([c.detail for c in found]))

st = first_telling(); dr.arm_retelling(st, "reverse_chronology")
found = retell(st, [{"text": "the cafe", "start_min": 18 * 60, "end_min": 20 * 60,
                     "location": "cafe"}])
check("saying LESS the second time is not a contradiction", not found,
      "recall is lossy and this is their second language - a thinner account is expected")

st = first_telling(); dr.arm_retelling(st, "reverse_chronology")
found = retell(st, [{"text": "the cafe, with Sam and Jo, it was raining",
                     "start_min": 18 * 60, "end_min": 20 * 60, "location": "cafe",
                     "people": ["Sam", "Jo"]}])
check("remembering MORE the second time is not a contradiction", not found,
      "recalling further detail on a later attempt is a marker of genuine memory")

st = first_telling(); dr.arm_retelling(st, "reverse_chronology")
found = retell(st, [{"text": "the cafe, sitting about", "start_min": 18 * 60,
                     "end_min": 20 * 60, "location": "cafe", "activity": "sitting about",
                     "people": ["Sam"]}])
check("different words for the same thing are not a contradiction", not found,
      "activity is free text; scoring it would call a synonym a lie")

st = first_telling(); dr.arm_retelling(st, "reverse_chronology")
found = retell(st, [{"text": "the cafe, ten past six", "start_min": 18 * 60 + 10,
                     "end_min": 20 * 60, "location": "cafe"}])
check("rounding a time slightly is not a contradiction", not found,
      f"a shift under {dr._RETELLING_TIME_SHIFT} minutes is ordinary imprecision")

# Ground they never covered the first time is news, not a discrepancy.
st = first_telling(); dr.arm_retelling(st, "reverse_chronology")
found = retell(st, [{"text": "before that I was at the station", "start_min": 17 * 60,
                     "end_min": 17 * 60 + 45, "location": "station"}])
check("new ground in the second telling is filed, not scored",
      not any(c.kind == "retelling" for c in found), str([c.detail for c in found]))

# One difference, raised once.
st = first_telling(); dr.arm_retelling(st, "reverse_chronology")
found = retell(st, [{"text": "I was at the bridge then", "start_min": 18 * 60,
                     "end_min": 20 * 60, "location": "bridge"}])
kinds = [c.kind for c in found]
check("a re-telling difference is not ALSO raised as a self-contradiction",
      kinds.count("retelling") == 1 and "self" not in kinds, str(kinds))

# Repeating yourself must not make the account look richer.
st = first_telling(); dr.arm_retelling(st, "reverse_chronology")
before = density.assess(st.claims)["the evening"].score
retell(st, [{"text": "I was at the cafe with Sam", "start_min": 18 * 60,
             "end_min": 20 * 60, "location": "cafe", "activity": "eating",
             "people": ["Sam"]}])
check("a repeat does not inflate detail density",
      density.assess(st.claims)["the evening"].score == before,
      "an account cannot get richer by being said twice")

# It is their story moving, so it lands where story movement lands.
st = InterviewState()
dr.update_pressure(st, [Contradiction(id="r", kind="retelling", turn_seq=1, detail="d")],
                   _an("I was at the bridge.", responsive=True), rep)
check("a re-telling difference raises pressure", st.pressure > 0)

st = InterviewState(stage=Stage.CLOSURE.value, pressure=0.8)
st.contradictions += [
    Contradiction(id="e", kind="evidence", turn_seq=1, detail="d", raised=True),
    Contradiction(id="r1", kind="retelling", turn_seq=2, detail="d"),
    Contradiction(id="r2", kind="retelling", turn_seq=3, detail="d"),
]
check("an account that fell apart under a second telling -> detained",
      dr.decide_outcome(st) == Outcome.DETAINED.value)

# Chen's trap has to survive the new route in.
st = first_telling()
st.claims[0].vouched_by_chen = True
dr.arm_retelling(st, "reverse_chronology")
found = retell(st, [{"text": "I was at the bridge then", "start_min": 18 * 60,
                     "end_min": 20 * 60, "location": "bridge"}])
check("breaking a claim Chen vouched for still springs the sting",
      any(c.was_vouched for c in found if c.kind == "retelling"))

# The window shuts when they have GIVEN the second telling, not when a timer
# expires. Without this the follow-up - the heaviest tactic in the registry -
# holds the floor for the rest of the interview.
st = first_telling(); dr.arm_retelling(st, "reverse_chronology")
opened_until, f = st.retelling_until_turn, st.retelling_from_turn
retell(st, [{"text": "the cafe again", "start_min": 18 * 60, "end_min": 20 * 60,
             "location": "cafe", "people": ["Sam"]}], turn=f + 1)
check("part-way through, the window stays open",
      st.retelling_until_turn == opened_until, f"until={st.retelling_until_turn}")

# A fluent learner can summarise the whole evening backwards in one message.
# That used to clear the coverage bar instantly and shut the window before the
# follow-up asked anything, so the second telling was measured on one paragraph.
retell(st, [{"text": "and home after", "start_min": 20 * 60, "end_min": 21 * 60,
             "location": "home"}], turn=f + 2)
check("covering it all at once does NOT cut the test short",
      st.retelling_until_turn == opened_until,
      "working through it step by step is the technique; a complete first "
      "answer is not a reason to stop asking")

retell(st, [{"text": "the cafe, like I said", "start_min": 18 * 60, "end_min": 20 * 60,
             "location": "cafe", "people": ["Sam"]}], turn=f + 3)
check("once it has been worked through, the window shuts early",
      st.retelling_until_turn < opened_until,
      f"until={st.retelling_until_turn}, opened_until={opened_until}")

# Measured in ground covered, not claims re-stated. An account built over many
# turns must not need one re-statement per turn to count as given again.
st = InterviewState(turn=6)
for n in range(6):                                   # six claims, one span
    dr.ingest(st, dr.Extraction(claims=[{"text": f"cafe {n}", "start_min": 18 * 60,
              "end_min": 20 * 60, "location": "cafe", "people": ["Sam"]}],
              topic="the cafe"), None, 6)
dr.arm_retelling(st, "reverse_chronology")
opened_until, f = st.retelling_until_turn, st.retelling_from_turn
for n in range(1, dr._RETELLING_MIN_TURNS + 1):
    retell(st, [{"text": "the cafe, six till eight", "start_min": 18 * 60,
                 "end_min": 20 * 60, "location": "cafe", "people": ["Sam"]}], turn=f + n)
check("re-covering the ground closes a span built over six turns",
      st.retelling_until_turn < opened_until,
      "counting claims rather than ground would set a bar nobody could clear")

# Loose vocabulary for the same people is not a swap of people.
st = InterviewState(turn=8)
dr.ingest(st, dr.Extraction(claims=[
    {"text": "drinks with work colleagues", "start_min": 17 * 60, "end_min": 18 * 60,
     "location": None, "place": "the pub", "people": ["work colleagues"]}],
    topic="the pub"), None, 8)
dr.arm_retelling(st, "reverse_chronology")
found = retell(st, [{"text": "I was with friends at the pub", "start_min": 17 * 60,
                     "end_min": 18 * 60, "place": "the pub", "people": ["friends"]}])
check("'colleagues' one telling and 'friends' the next is not a lie",
      not [c for c in found if c.kind == "retelling"],
      "neither names anybody; loose vocabulary is not a different set of people")


print("\nSEQUENCE PRESSURE  (more anchors than a story can be narrated around)")

sparse_claims = [Claim(id=f"s{i}", turn_seq=i, text=f"block {i}",
                       start_min=(17 + i) * 60, end_min=(18 + i) * 60,
                       location="cafe", topic="the evening") for i in range(3)]
check("three blocks yield few timepoints", density.timepoints(sparse_claims) == 4)

c, st = ctx_with(Stage.PROBE, sparse_claims)
ids = {t.id for t in tac.available(c, "Reynolds")}
check("a sparse timeline offers sequence extraction", "elicit_sequence" in ids,
      str(sorted(ids)))
check("and the forced choice is on the table", "forced_choice" in ids)

dense_claims = sparse_claims + [
    Claim(id=f"d{i}", turn_seq=5, text=f"event {i}", start_min=17 * 60 + i * 17,
          location="cafe", topic="the evening") for i in range(4)]
c, st = ctx_with(Stage.PROBE, dense_claims)
check("enough anchors and it stands down",
      "elicit_sequence" not in {t.id for t in tac.available(c, "Reynolds")},
      f"timepoints={density.timepoints(dense_claims)}")

check("saying 'about half six' four times is ONE anchor, not four",
      density.timepoints([Claim(id=f"r{i}", turn_seq=i, text="half six",
                                start_min=18 * 60 + 30) for i in range(4)]) == 1)

# The depth-follower must actually win a slot once nothing is thin AND the
# timeline is anchored - before that, sequence extraction rightly outranks it.
anchored = full_rich + [probed(f"t{i}", 17, i * 7, 17, i * 7 + 5, "cafe",
                               "the cafe", seq=5) for i in range(3)]
c, st = ctx_with(Stage.PROBE, anchored)
offered = [t.id for t in tac.available(c, "Chen")]
check("volunteered detail gets followed one layer deeper",
      "detail_expansion" in offered[:3], str(offered[:5]))

# A challenge needs air around it.
c, st = ctx_with(Stage.CHALLENGE, full_rich)
st.contradictions.append(Contradiction(id="x", kind="self", turn_seq=1, detail="d"))
c = dr.build_context(st, None)
check("challenge_contradiction now carries a cooldown",
      tac.get("challenge_contradiction").cooldown >= 2)


# Tactic gating around the mode.
c, st = ctx_with(Stage.PROBE, full_rich)
st.turn = 5
st.retelling_from_turn, st.retelling_until_turn = 4, 10
c = dr.build_context(st, None)
ids = {t.id for t in tac.available(c, "Reynolds")}
check("mid-re-telling, the follow-up is offered", "retelling_followup" in ids, str(sorted(ids)))
check("and it will not ask for a SECOND second telling",
      "reverse_chronology" not in ids and "retell_from_point" not in ids, str(sorted(ids)))

# Backwards, then outward from a point, and that is the repertoire. Each costs
# several turns of an interview capped at forty.
c, st = ctx_with(Stage.CHALLENGE, full_rich)
st.turn = 20
st.retellings_asked = 2
c = dr.build_context(st, None)
ids = {t.id for t in tac.available(c, "Reynolds")}
check("having asked twice, they stop asking",
      "reverse_chronology" not in ids and "retell_from_point" not in ids,
      "a third request is badgering, not technique")


print("\nFALSE-PREMISE PROBE  (the engine misremembers; do they notice?)")


def storied(turn=6):
    """An account with a stated time and two places - material for a misquote."""
    st = InterviewState(turn=turn)
    dr.ingest(st, dr.Extraction(claims=[
        {"text": "I was at the cafe until quarter to eight", "end_min": 19 * 60 + 45,
         "location": "cafe", "place": "the cafe", "people": ["Sam"]},
        {"text": "then dinner at the Indian restaurant", "start_min": 20 * 60,
         "place": "the Indian restaurant"},
    ], topic="the evening"), None, 3)
    return st


st = storied()
p = dr.plan_false_premise(st)
check("a misquote is authored from their own claim", p is not None)
check("the shifted time is an hour out, not a rounding",
      p["kind"] == "time" and abs(p["true_min"] - (19 * 60 + 45)) == 0
      and "18:45" in p["false"], str(p))
check("a departure is misquoted as leaving, not arriving", "left" in p["false"], p["false"])
check("their actual words ride along for the model", p["quote"].startswith("I was at the cafe"))

st = storied()
st.premises_posed = 1
p2 = dr.plan_false_premise(st)
check("the second probe draws a different misstatement", p2 != dr.plan_false_premise(storied()))

st = storied()
st.premise_open = {"posed_turn": 5}
check("no new probe while one is pending", dr.plan_false_premise(st) is None)
st.premise_open = None
st.premises_posed = dr.MAX_PREMISES
check("and the probe is spent after two", dr.plan_false_premise(st) is None)

check("nothing to draw on -> no probe",
      dr.plan_false_premise(InterviewState(turn=6)) is None,
      "the probe misremembers; it never invents")

# Availability follows the plan.
c, st = ctx_with(Stage.PROBE, full_rich)
c = dr.build_context(st, None)
check("the tactic is offered when a misquote exists",
      "false_premise" in {t.id for t in tac.available(c, "Reynolds")})
st.premises_posed = dr.MAX_PREMISES
c = dr.build_context(st, None)
check("and withdrawn once spent",
      "false_premise" not in {t.id for t in tac.available(c, "Reynolds")})

# Scoring. Catching is credited; missing costs nothing at all.
st = storied()
st.premise_open = {"claim_id": "x", "kind": "time", "true_min": 19 * 60 + 45,
                   "false": "you left at about 18:45", "quote": "q", "posed_turn": 6}
st.turn = 7
before_exc, before_pressure = st.exculpation, st.pressure
caught = dr.resolve_premise(st, True, [])
check("a correction the model saw is caught", caught is True and st.premises_caught == 1)
check("and credited as truthful recall", st.exculpation > before_exc)

st = storied()
st.premise_open = {"claim_id": "x", "kind": "time", "true_min": 19 * 60 + 45,
                   "false": "f", "quote": "q", "posed_turn": 6}
st.turn = 7
fresh = [Claim(id="r", turn_seq=7, text="no, quarter to eight", end_min=19 * 60 + 45)]
check("restating the true time is a correction even if the model missed it",
      dr.resolve_premise(st, None, fresh) is True)

st = storied()
st.premise_open = {"claim_id": "x", "kind": "time", "true_min": 19 * 60 + 45,
                   "false": "f", "quote": "q", "posed_turn": 6}
st.turn = 7
before_exc, before_pressure = st.exculpation, st.pressure
caught = dr.resolve_premise(st, False, [])
check("letting it slide is recorded as a miss",
      caught is False and st.premises_missed == 1)
check("and costs NOTHING - no pressure, no lost credit",
      st.pressure == before_pressure and st.exculpation == before_exc,
      "an L2 learner missing a misquote may be comprehension, not acquiescence")
check("either way the probe closes", st.premise_open is None)

# Acquiescing to the planted misquote must not convict them. The learner echoes
# the false time back rather than correcting it; ingest must not read that as a
# spontaneous self-contradiction against the claim the engine itself misquoted.
st = storied()
cafe = st.claims[0]                                  # "...cafe until quarter to eight" (19:45)
st.premise_open = {"claim_id": cafe.id, "kind": "time", "true_min": 19 * 60 + 45,
                   "false": "you left the cafe at about 18:45", "quote": cafe.text,
                   "posed_turn": 6}
st.turn = 7
before_pressure = st.pressure
echo = dr.ingest(st, dr.Extraction(claims=[
    {"text": "yes, I left about quarter to seven", "end_min": 18 * 60 + 45,
     "location": "cafe", "place": "the cafe"}]), None, 7)
check("echoing a planted misquote mints no contradiction",
      not [c for c in echo if c.kind in ("self", "retelling")],
      str([(c.kind, c.detail[:50]) for c in echo]))
check("and does not supersede their true statement", cafe.superseded_by is None)
dr.resolve_premise(st, False, st.claims[-1:])
dr.update_pressure(st, echo, _an("x", responsive=True), tl.build(st.claims))
check("acquiescing to the misquote costs no pressure",
      st.pressure <= before_pressure,
      "letting a misquote slide may be comprehension, not a lie")

# A genuine contradiction on a DIFFERENT claim is still caught while a probe is
# open - the guard is scoped to the one misquoted claim, not a free pass.
st = storied()
cafe = st.claims[0]
st.premise_open = {"claim_id": cafe.id, "kind": "time", "true_min": 19 * 60 + 45,
                   "false": "you left the cafe at about 18:45", "quote": cafe.text,
                   "posed_turn": 6}
st.turn = 7
other = dr.ingest(st, dr.Extraction(claims=[
    {"text": "the Indian place, we got there about half nine", "start_min": 21 * 60 + 30,
     "place": "the Indian restaurant"}]), None, 7)
check("a contradiction on a different claim still fires while a probe is open",
      any(c.kind == "self" for c in other), str([c.detail[:50] for c in other]))


print("\nTACTIC VALIDATION  (the model may only use what it was offered)")

from agent import _validated_tactic                     # noqa: E402


class _T:                                               # minimal stand-in for a Tactic
    def __init__(self, tid): self.id = tid


offered = [_T("funnel_probe"), _T("detail_expansion"), _T("forced_choice")]
check("an offered tactic passes through",
      _validated_tactic("detail_expansion", offered) == "detail_expansion")
check("bracket echoes are stripped",
      _validated_tactic("[funnel_probe]", offered) == "funnel_probe")
check("an unoffered tactic collapses to the top offer",
      _validated_tactic("challenge_contradiction", offered) == "funnel_probe",
      "a phantom challenge would mark evidence raised and flip the verdict")
check("a hallucinated id collapses too",
      _validated_tactic("interrogate_harder", offered) == "funnel_probe")
check("with no shortlist the cleaned value passes through",
      _validated_tactic("anything", []) == "anything")
check("empty stays empty", _validated_tactic("", offered) == "funnel_probe"
      and _validated_tactic(None, []) == "")

st = storied()
st.premise_open = {"claim_id": "x", "kind": "time", "true_min": 19 * 60 + 45,
                   "false": "f", "quote": "q", "posed_turn": 6}
st.turn = 6
check("never scored on the turn it was posed",
      dr.resolve_premise(st, True, []) is None and st.premise_open is not None,
      "their answer has not arrived yet")

# The pending probe survives a resume.
st = storied()
st.premise_open = {"claim_id": "x", "kind": "time", "true_min": 100,
                   "false": "f", "quote": "q", "posed_turn": 6}
st.premises_posed = 1
round_tripped = InterviewState.from_dict(st.to_dict())
check("a pending probe survives the JSON round-trip",
      round_tripped.premise_open == st.premise_open
      and round_tripped.premises_posed == 1)


print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
