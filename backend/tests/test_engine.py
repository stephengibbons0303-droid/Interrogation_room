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


print("\nDETAIL DENSITY  (what makes probing directed)")

sparse = [Claim(id="1", turn_seq=1, text="I was at the cafe.",
                location="cafe", topic="the cafe")]
d = density.assess(sparse)["the cafe"]
check("a bare topic is thin", d.thin, f"score={d.score}")
check("and it names what is missing",
      any("nobody named" in m for m in d.missing()), str(d.missing()))
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

check("one rich topic is not yet a testable account",
      not density.testable(full_rich[:2]))
check("two rich topics are", density.testable(full_rich))
check("a bare account is never testable however much time it covers",
      not density.testable(full_blocks))

# Density must never be a stick. It says where to ask next, and nothing else.
st = InterviewState()
before = st.pressure
dr.update_pressure(st, [], _an("Yes.", responsive=True), tl.build(sparse))
check("a thin account does NOT raise pressure", st.pressure <= before,
      "a learner short of vocabulary is doing the thing the app exists to make them do")


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
    return st, dr.ingest(st, dr.Extraction(claims=claims),
                         _an("x", responsive=True), brief, 1)


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
          _an("x", responsive=True), canal, 2)
check("conceding it twice is still one breach",
      len([c for c in st.contradictions if c.kind == "breach"]) == 1)

# Density is measured per topic, so the tag has to survive ingest - otherwise
# every claim lands in one bucket and no topic ever reads as thin.
st = InterviewState()
dr.ingest(st, dr.Extraction(claims=[{"text": "the cafe was busy", "location": "cafe"}],
                            topic="the cafe"), _an("x", responsive=True), canal, 1)
check("the live topic is carried onto the claim", st.claims[0].topic == "the cafe")

st = InterviewState(current_topic="the walk home")
dr.ingest(st, dr.Extraction(claims=[{"text": "it was raining", "location": "home"}]),
          _an("x", responsive=True), canal, 1)
check("a claim with no topic named falls to the topic already running",
      st.claims[0].topic == "the walk home")

check("a retired brief id deals a pair rather than stranding the interview",
      briefs_mod.get("innocent_missed_calls") is not None)
check("and the same retired id always deals the same pair",
      briefs_mod.get("innocent_missed_calls").id
      == briefs_mod.get("innocent_missed_calls").id)


print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
if FAIL:
    print("FAILED: " + ", ".join(FAIL))
sys.exit(1 if FAIL else 0)
