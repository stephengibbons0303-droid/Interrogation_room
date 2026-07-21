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
from scenario.briefs import BRIEFS                      # noqa: E402


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
ready, _ = ctx_with(Stage.PROBE, full_blocks)
ids = {t.id for t in tac.available(ready, "Reynolds")}
check("reverse chronology UNLOCKED once the timeline is complete", "reverse_chronology" in ids)

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
check("evidence contradiction raises pressure most", st.pressure >= 0.2)


print("\nSPEAKER SPLIT  (triggers, not chance)")

st = InterviewState(stage=Stage.PROBE.value)
st.claims = list(full_blocks)
st.topics_covered = ["identity", "relationship"]
reasons = {}
for i in range(60):
    if i % 9 == 0:                       # evidence becomes due
        st.contradictions.append(Contradiction(id=f"x{i}", kind="evidence",
                                               turn_seq=i, detail="d"))
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
check("shaky account -> under investigation",
      dr.decide_outcome(st) == Outcome.UNDER_INVESTIGATION.value)

st = InterviewState(stage=Stage.CLOSURE.value, pressure=0.8)
st.contradictions.append(Contradiction(id="e", kind="evidence", turn_seq=1, detail="d"))
check("caught out on evidence -> detained", dr.decide_outcome(st) == Outcome.DETAINED.value)

st = InterviewState(stage=Stage.PROBE.value, pressure=0.9)
check("no outcome before closure", dr.decide_outcome(st) is None)


print("\nEVIDENCE FRAMING MATRIX")

st = InterviewState()
st.contradictions.append(Contradiction(id="c", kind="evidence", turn_seq=1,
                                       detail="d", evidence_id="cell_tower"))
first = dr.next_disclosure(st)
check("evidence is first put vaguely", first == ("cell_tower", "vague"), str(first))
st.disclosed["cell_tower"] = "vague"
check("then moderately", dr.next_disclosure(st) == ("cell_tower", "moderate"))
st.disclosed["cell_tower"] = "moderate"
check("then precisely", dr.next_disclosure(st) == ("cell_tower", "precise"))
st.disclosed["cell_tower"] = "precise"
check("and never beyond precise", dr.next_disclosure(st) == ("cell_tower", "precise"))


print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
