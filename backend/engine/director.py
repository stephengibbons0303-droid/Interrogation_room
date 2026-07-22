"""The director: who speaks, what they do, how much trouble the learner is in.

Everything here is deterministic and inspectable. The model is left with the one
job it is actually better at - saying the thing well - while the decisions that
need to be consistent, gated and testable are made in Python.
"""
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from scenario import case
from scenario.briefs import Brief
from engine import density
from engine import tactics as tac
from engine.analysis import TurnAnalysis
from engine.state import (CHEN_ARC, STAGE_ORDER, ChenStance, Claim,
                          Contradiction, InterviewState, Outcome, Stage)
from engine.timeline import (TimelineReport, build as build_timeline,
                             fmt as _fmt, normalised as normalise)

LEAD = "Reynolds"
SECOND = "Chen"

# The researched division of labour: the lead takes roughly three turns in four.
# Used only as a nudge - triggers below take precedence, because the document is
# clear that hand-offs happen for reasons, not on a quota.
LEAD_SHARE_TARGET = 0.75

MAX_TURNS = 40

# How long the probe stage will wait for an account worth attacking before moving
# on regardless. Without this, a learner who cannot produce much detail would be
# held in probing indefinitely - a longer, flatter interview as a punishment for
# lower proficiency, which is exactly backwards.
PROBE_PATIENCE = 18

# Turns a second telling stays live once asked for. An evening takes several
# turns to walk through again; after that the mode lapses rather than treating
# everything said for the rest of the interview as a re-statement.
RETELLING_TURNS = 6

# Tactics that ask for the account again. Firing one of these arms the mode.
RETELLING_TACTICS = {"reverse_chronology", "retell_from_point"}



# How far a stated time may move between tellings before it is a real change.
# People round, and "about nine" one minute is "half nine" the next without
# anybody lying; the threshold has to clear ordinary imprecision.
_RETELLING_TIME_SHIFT = 30

# How much of the first telling has to be gone over again before the second one
# counts as given. Measured in ground covered rather than claims re-stated: an
# account of four stretches of the evening might have been built over ten turns,
# and demanding ten re-statements would be a bar nobody could clear.
_RETELLING_DONE = 0.8


# ── speaker selection ────────────────────────────────────────────────────────

def select_speaker(ctx: tac.Context) -> Tuple[str, str]:
    """Pick the next speaker via the five documented trigger points.

    Returns (speaker, reason). Reason is recorded so the split can be audited -
    a run where every hand-off says "ratio" means the triggers are not firing.
    """
    s = ctx.state

    # 1. Rapport needs reinforcement. Highest priority: a learner who has lost
    #    the thread must not be handed to the bad cop.
    if ctx.last_learner_struggling or s.nonresponsive_streak >= 2:
        return SECOND, "rapport"

    # 2. Specific evidence is due - assigned to the lead during planning.
    if Stage(s.stage) == Stage.CHALLENGE and any(
            c.kind == "evidence" and not c.raised for c in s.contradictions):
        return LEAD, "evidence"

    # 3. The dynamic has stalled - the other interviewer may get somewhere.
    if s.last_speaker and s.consecutive_speaker >= 3:
        return (SECOND if s.last_speaker == LEAD else LEAD), "stall"

    # 4. End of a topic segment - the natural break for the second interviewer.
    if s.current_topic is None and s.topics_covered:
        return SECOND, "topic_end"

    # 5. Clarification needed: they answered, but not the question asked.
    if not ctx.last_learner_evasive and s.nonresponsive_streak == 1:
        return SECOND, "clarify"

    # Otherwise hold the researched ratio.
    return (SECOND if s.lead_share() > LEAD_SHARE_TARGET else LEAD), "ratio"


def note_speaker(state: InterviewState, speaker: str) -> None:
    """Record who spoke, for the stall trigger and the 75/25 ratio."""
    state.consecutive_speaker = (
        state.consecutive_speaker + 1 if state.last_speaker == speaker else 1)
    state.last_speaker = speaker
    state.speaker_counts[speaker] = state.speaker_counts.get(speaker, 0) + 1


# ── tactic shortlisting ──────────────────────────────────────────────────────

def shortlist(ctx: tac.Context, speaker: str, limit: int = 3) -> List[tac.Tactic]:
    """The tactics the model may choose between this turn.

    Offering a shortlist rather than one tactic keeps the fine judgement with the
    model while the hard constraints - stage, precondition, cooldown - stay
    enforced here. The model reports which it used so cooldowns are real.
    """
    options = tac.available(ctx, speaker)
    if not options:                        # never leave a speaker with nothing
        fallback = tac.get("funnel_probe") if Stage(ctx.state.stage) != Stage.CLOSURE \
            else tac.get("closure_summary")
        return [fallback] if fallback else []
    return options[:limit]


# ── ingesting what the learner said ──────────────────────────────────────────

@dataclass
class Extraction:
    """The structured half of the model's reply - what the learner committed to."""
    claims: List[Dict[str, Any]]
    responsive: bool = True
    topic: Optional[str] = None
    topic_complete: bool = False
    chen_vouched_claim: bool = False       # Chen pushed them to commit to this


def arm_retelling(state: InterviewState, tactic_id: str) -> None:
    """A detective has just asked for the account again. Open the window.

    Called after the turn's claims have been folded in, because the message
    being ingested is their answer to the PREVIOUS question - the re-telling
    itself does not arrive until the turn after this one.
    """
    if tactic_id in RETELLING_TACTICS:
        state.retelling_from_turn = state.turn
        state.retelling_until_turn = state.turn + RETELLING_TURNS
        state.retellings_asked += 1


def _first_telling(state: InterviewState, before_turn: int) -> List[Claim]:
    """The account as it stood before they were asked to give it again."""
    return [c for c in normalise(state.claims)
            if c.turn_seq <= before_turn and not c.restates]


def _covered_minutes(claims: List[Claim]) -> int:
    """Minutes of the evening these claims account for, overlaps merged once."""
    spans = sorted((c.start_min, c.end_min) for c in claims if c.has_window)
    merged: List[List[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(e - s for s, e in merged)


def _match_original(state: InterviewState, claim: Claim,
                    before_turn: int) -> Optional[Claim]:
    """Which part of the first telling is this re-stating?

    Matched on time, because an evening is a timeline and a second telling
    revisits stretches of it. The best overlap wins; no overlap at all means
    they have wandered onto ground they never covered, which is new information
    rather than a re-statement.
    """
    if not claim.has_window:
        return None
    best, best_overlap = None, 0
    for prior in _first_telling(state, before_turn):
        overlap = min(prior.end_min, claim.end_min) - max(prior.start_min, claim.start_min)
        if overlap > best_overlap:
            best, best_overlap = prior, overlap
    return best


def _retelling_conflicts(state: InterviewState, claim: Claim, original: Claim,
                         turn_seq: int) -> List[Contradiction]:
    """Score the delta between telling one and telling two.

    Vrij et al. (2008): reverse recall is hard for liars because they rehearsed
    forwards, and hard for truth-tellers too - which is the point. The
    difficulty is real either way, and what separates them is whether the
    CONTENT holds. So only content that genuinely conflicts is scored here.

    Three things are deliberately NOT scored, and each of them would otherwise
    punish an honest learner:

      * Saying LESS. Recall is lossy and this is their second language under
        pressure; a thinner account is expected, not evasive.
      * Saying MORE. Recalling further detail on a later attempt is well
        established and is a marker of genuine memory, not invention.
      * Different words for the same thing. `activity` is free text, so
        "waiting" against "sitting about" would read as a lie about wording.

    What is left is substitution: they said one thing, now they say another.
    """
    out: List[Contradiction] = []
    prior_row = state.claim(original.id)
    vouched = bool(prior_row and prior_row.vouched_by_chen)

    def flag(detail: str) -> None:
        out.append(Contradiction(
            id=str(uuid.uuid4()), kind="retelling", turn_seq=turn_seq,
            detail=detail, claim_id=claim.id, against_claim_id=original.id,
            was_vouched=vouched,
        ))

    if claim.location and original.location and claim.location != original.location:
        flag(f"telling it again, '{original.text}' has become '{claim.text}' - "
             f"{original.location} the first time, {claim.location} now")

    # Stated bounds only. An invented bound is the timeline being helpful, and
    # accusing someone of moving a time the engine supplied itself is the
    # failure this codebase keeps having to guard against.
    if not claim.inferred and not original.inferred:
        shift = abs(claim.start_min - original.start_min)
        if shift >= _RETELLING_TIME_SHIFT and claim.location == original.location:
            flag(f"'{original.text}' was put at {_fmt(original.start_min)} the first "
                 f"time and {_fmt(claim.start_min)} now - {shift} minutes adrift")

    # Only a straight swap counts: both tellings name somebody, and not one name
    # survives. Dropping a name is forgetting; adding one is remembering.
    first_names = {p.strip().lower() for p in original.people if p and p.strip()}
    now_names = {p.strip().lower() for p in claim.people if p and p.strip()}
    if first_names and now_names and not (first_names & now_names):
        flag(f"'{original.text}' had {', '.join(sorted(first_names))} in it; "
             f"now it is {', '.join(sorted(now_names))}")

    return out


def ingest(state: InterviewState, extraction: Extraction, analysis: TurnAnalysis,
           brief: Optional[Brief], turn_seq: int) -> List[Contradiction]:
    """Fold a learner turn into state and return any NEW contradictions."""
    found: List[Contradiction] = []

    # Settled before the claims are built: density is measured per topic, and the
    # only moment a claim's topic is known for certain is the turn it arrived on.
    topic = extraction.topic or state.current_topic

    new_ids = []
    for raw in extraction.claims:
        claim = Claim(
            id=str(uuid.uuid4()),
            turn_seq=turn_seq,
            text=raw.get("text", "")[:500],
            start_min=raw.get("start_min"),
            end_min=raw.get("end_min"),
            location=raw.get("location"),
            activity=raw.get("activity"),
            people=raw.get("people") or [],
            topic=topic,
            vouched_by_chen=extraction.chen_vouched_claim,
        )
        state.claims.append(claim)
        new_ids.append(claim.id)

        # A breach is checked on the RAW claim, before the timeline fills in the
        # bound speech left out. Conceding the concealed place at a time they
        # actually stated is their own admission; an invented bound is the engine
        # guessing, and the engine does not get to extract a confession from its
        # own arithmetic.
        if brief is not None:
            stated = claim.start_min if claim.start_min is not None else claim.end_min
            if brief.breached_by(claim.location, stated) and not any(
                    c.kind == "breach" for c in state.contradictions + found):
                found.append(Contradiction(
                    id=str(uuid.uuid4()), kind="breach", turn_seq=turn_seq,
                    detail=f"they have placed themselves there: '{claim.text}'",
                    claim_id=claim.id,
                ))

    # Detection runs over NORMALISED claims: speech gives one bound, not two, so
    # comparing raw windows found nothing at all. See timeline.normalised.
    spans = {c.id: c for c in normalise(state.claims)}

    # Is this the second telling? If so, what they say is measured against the
    # first one instead of being filed as further information - which is the
    # entire mechanic. Told forwards then backwards, an account that holds is
    # the same account; one that does not is where the interview turns.
    retelling = state.is_retelling(turn_seq)
    baseline_turn = state.retelling_from_turn if retelling else turn_seq

    for cid in new_ids:
        claim = spans.get(cid)
        if claim is None:                      # no time information at all
            continue
        original = state.claim(cid)

        matched = _match_original(state, claim, baseline_turn) if retelling else None
        if matched is not None:
            if original is not None:
                original.restates = matched.id
            found.extend(_retelling_conflicts(state, claim, matched, turn_seq))

        # Self-contradiction: does this replace something they already said?
        # Skipped for a re-statement, which has just been measured against the
        # first telling - running both would raise one difference twice. The
        # evidence pass below still runs either way: a second telling can move
        # them somewhere they had not walked into before, and that is news.
        for prior in (normalise(state.claims) if matched is None else []):
            if prior.id == cid or prior.turn_seq >= claim.turn_seq:
                continue
            if not (prior.location and claim.location) or prior.location == claim.location:
                continue
            if prior.start_min < claim.end_min and claim.start_min < prior.end_min:
                prior_row = state.claim(prior.id)
                if prior_row is None or prior_row.superseded_by:
                    continue
                prior_row.superseded_by = cid
                found.append(Contradiction(
                    id=str(uuid.uuid4()), kind="self", turn_seq=turn_seq,
                    detail=f"earlier: '{prior.text}' - now: '{claim.text}'",
                    claim_id=cid, against_claim_id=prior.id,
                    was_vouched=prior_row.vouched_by_chen,
                ))

        # There is deliberately no check here for the account departing from what
        # "really" happened. Under the dealt-account design that was the central
        # test; now the evening is the learner's own invention, so there is no
        # external truth for it to depart from. The only fixed facts are the
        # concealment pair, and conceding one of those is handled above as a
        # breach - on their own words rather than on the engine knowing better.

        # Against the evidence - what makes SUE mechanical rather than
        # hand-written: they commit, and the engine knows what they walked into.
        from datetime import time as _t
        window = (_t(claim.start_min // 60 % 24, claim.start_min % 60),
                  _t(min(claim.end_min, 23 * 60 + 59) // 60 % 24, claim.end_min % 60))
        for ev in case.evidence_for(window, claim.location):
            if ev.id in state.disclosed:
                continue
            if any(c.evidence_id == ev.id for c in state.contradictions + found):
                continue
            found.append(Contradiction(
                id=str(uuid.uuid4()), kind="evidence", turn_seq=turn_seq,
                detail=f"'{claim.text}' does not sit with: {ev.fact}",
                claim_id=cid, evidence_id=ev.id,
            ))

    # A second telling ends when they have given it, not when a timer runs out.
    # Once every stretch of the first account has been gone over again there is
    # nothing left to compare, and leaving the window open would let the
    # follow-up - the heaviest tactic in the registry - hold the floor for the
    # rest of the interview. RETELLING_TURNS stays as the backstop for a learner
    # who wanders off and never finishes.
    if retelling:
        first = _first_telling(state, baseline_turn)
        revisited = {c.restates for c in state.claims
                     if c.restates and c.turn_seq > baseline_turn}
        total = _covered_minutes(first)
        if total and _covered_minutes([c for c in first if c.id in revisited]) \
                >= _RETELLING_DONE * total:
            state.retelling_until_turn = turn_seq

    state.contradictions.extend(found)

    if extraction.topic:
        state.current_topic = None if extraction.topic_complete else extraction.topic
        if extraction.topic_complete and extraction.topic not in state.topics_covered:
            state.topics_covered.append(extraction.topic)

    state.nonresponsive_streak = 0 if extraction.responsive else state.nonresponsive_streak + 1
    return found


# ── pressure ─────────────────────────────────────────────────────────────────

# Pressure may only come from things the detectives could actually perceive.
#
# A breach is the one thing here they hear directly - the learner has just placed
# themselves at the concealed spot in their own words. It still scores modestly
# rather than decisively. The consequence of conceding belongs in the ending, not
# in a spike that slams pressure to the ceiling the moment it happens; a learner
# who lets it slip and then holds everything else together should feel the room
# change, not lose on the spot.
#
# There is no "brief" entry any more. Departing from a dealt account was the old
# test, and there is no dealt account to depart from.
#
# A retelling difference scores highest of the three the learner controls. It is
# the sharpest thing an interviewer can get: not a slip noticed in passing, but
# the account failing under a test it was deliberately put to.
_PRESSURE_FOR = {"self": 0.10, "breach": 0.10, "retelling": 0.12, "evidence": 0.15}

# Their own account moving, however it was caught. Kept as one set because the
# ending should not care whether a difference surfaced on its own or under a
# second telling - only that the story did not hold.
_WOBBLE_KINDS = ("self", "retelling")

# One bad turn should not end the interview. Several claims can clash with the
# same story, and without a ceiling they compound into an instant conviction.
_MAX_PRESSURE_PER_TURN = 0.22


def update_pressure(state: InterviewState, new_contradictions: List[Contradiction],
                    analysis: TurnAnalysis, report: TimelineReport) -> None:
    """Move pressure and exculpation.

    Only things visible from across the table count: an account that changes,
    an account that collides with evidence, unaccounted time, and deliberate
    evasion. Language quality is deliberately absent - a learner struggling for
    words is doing the thing the app exists to make them do.
    """
    gain = 0.0
    for c in new_contradictions:
        gain += _PRESSURE_FOR.get(c.kind, 0.05)

    if report.gaps:
        gain += min(0.02 * len(report.gaps), 0.04)
    if report.impossible:
        gain += 0.05
    if analysis.evasive:
        gain += 0.06
        state.evasions += 1

    state.pressure += min(gain, _MAX_PRESSURE_PER_TURN)

    # Detail and cooperation buy relief. Richness never subtracts, so a poor
    # answer costs nothing - it simply earns nothing.
    state.exculpation += analysis.richness * 0.06
    if not new_contradictions and analysis.responsive:
        state.pressure -= 0.03
    state.exculpation += report.coverage * 0.01

    state.pressure = max(0.0, min(1.0, state.pressure))
    state.exculpation = max(0.0, min(1.0, state.exculpation))


# ── Chen's arc ───────────────────────────────────────────────────────────────

def update_chen(state: InterviewState, new_contradictions: List[Contradiction],
                ctx_struggling: bool) -> bool:
    """Advance Chen's stance. Returns True if the sting just fired.

    The sting is not a stage of the arc - it is a trap springing. It fires only
    when a claim SHE talked them into committing to is the one that breaks,
    which is what turns her earlier warmth into something they should have
    been more careful about.
    """
    stance = ChenStance(state.chen_stance)

    if stance is not ChenStance.STING:
        for c in new_contradictions:
            if c.was_vouched:
                state.chen_stance = ChenStance.STING.value
                return True

    if stance is ChenStance.STING:
        return False

    target = stance
    if stance is ChenStance.NEUTRAL and state.turn >= 2:
        target = ChenStance.RAPPORT
    if stance is ChenStance.RAPPORT and (ctx_struggling or state.pressure >= 0.2):
        target = ChenStance.ADVOCATE
    if stance is ChenStance.ADVOCATE and state.pressure >= 0.4:
        target = ChenStance.IDENTIFYING
    if stance is ChenStance.IDENTIFYING and state.pressure >= 0.6 \
            and Stage(state.stage) is Stage.CHALLENGE:
        target = ChenStance.MINIMISING

    # One step at a time, and never backwards - her warmth should not flicker.
    if target is not stance and CHEN_ARC.index(target) > CHEN_ARC.index(stance):
        state.chen_stance = target.value
    return False


# ── stage and endgame ────────────────────────────────────────────────────────

def advance_stage(state: InterviewState, report: TimelineReport) -> None:
    """Move through PEACE on procedure, not on a turn counter."""
    stage = Stage(state.stage)

    if stage is Stage.ENGAGE and state.turn >= 2:
        stage = Stage.FREE_RECALL
    elif stage is Stage.FREE_RECALL and (report.blocks or state.turn >= 5):
        stage = Stage.PROBE
    # Probing does not end because enough ground has been covered - it ends when
    # the account is dense enough to be worth attacking. Challenging a list of
    # bare assertions is what made the techniques fire into a vacuum. The
    # patience limit is the escape hatch: a learner who cannot produce detail is
    # moved on rather than held here.
    elif stage is Stage.PROBE and report.complete and (
            state.contradictions or len(state.topics_covered) >= 3) and (
            density.testable(state.claims) or state.turn >= PROBE_PATIENCE):
        stage = Stage.CHALLENGE
    elif stage is Stage.CHALLENGE and (
            (not state.open_contradictions and state.turn >= 14)
            or state.pressure >= 0.9
            or state.turn >= MAX_TURNS):
        stage = Stage.CLOSURE

    if stage.value != state.stage:
        state.stage = stage.value
        state.asides_this_stage = 0


def decide_outcome(state: InterviewState) -> Optional[str]:
    """What happens to them. Only meaningful once Closure is reached.

    Everyone is concealing now, so "did they lie" is no longer the question - it
    is a given, and judging on it would detain every learner every time. The
    question is whether their own account gave them away:

      * they conceded the concealed fact (a breach - their own words), or
      * their story moved under them and evidence was put to them on it, or
      * they would not talk at all.

    Holding both halves of the pair together for a whole interview is a win, and
    it walks them out of the building - however badly the evidence reads. That is
    the point of the shift: the ending turns on what the learner did, never on
    what the engine happens to know about where they were.
    """
    if Stage(state.stage) is not Stage.CLOSURE:
        return None

    caught = [c for c in state.contradictions if c.kind == "evidence" and c.raised]
    wobbled = [c for c in state.contradictions if c.kind in _WOBBLE_KINDS]
    breached = [c for c in state.contradictions if c.kind == "breach"]

    # They put themselves there. With anything to corroborate it, that is enough
    # to hold them; on its own it is an admission and no more.
    if breached:
        return (Outcome.DETAINED.value
                if (caught or wobbled)
                else Outcome.UNDER_INVESTIGATION.value)

    # Walking into the evidence does NOT decide this, and that is deliberate.
    #
    # Every item that can clash sits at the bridge between 21:15 and 22:20, which
    # is the same span every brief tells them to conceal. So a cover story is
    # guaranteed to collide with the mast data - concealing perfectly and
    # concealing badly look identical here. Letting the collision decide the
    # ending would mean the only way to walk was to give no account of that hour
    # at all, which rewards saying as little as possible: the exact opposite of
    # what this app is for. The collision is what the interview FEELS like; it is
    # not what the verdict is made of.
    #
    # The verdict is made of what they did with their own account: whether they
    # conceded it, whether it moved under them, whether they would talk at all.
    if len(wobbled) >= 2 and caught:
        return Outcome.DETAINED.value
    if wobbled or state.evasions >= 3:
        return Outcome.UNDER_INVESTIGATION.value
    return Outcome.RELEASED.value


# ── next evidence to put ─────────────────────────────────────────────────────

_LEVELS = ["vague", "moderate", "precise"]


def next_disclosure(state: InterviewState) -> Optional[Tuple[str, str]]:
    """The evidence item to put next, and how precisely to put it.

    The Evidence Framing Matrix: the same item is introduced vaguely, then
    moderately, then precisely, so the learner keeps having to account for it
    with progressively less room.
    """
    for c in state.contradictions:
        if c.kind != "evidence" or c.raised or not c.evidence_id:
            continue
        current = state.disclosed.get(c.evidence_id)
        nxt = _LEVELS[0] if current is None else (
            _LEVELS[min(_LEVELS.index(current) + 1, len(_LEVELS) - 1)])
        return c.evidence_id, nxt
    return None


def build_context(state: InterviewState, brief: Optional[Brief],
                  analysis: Optional[TurnAnalysis] = None) -> tac.Context:
    report = build_timeline(state.claims)
    return tac.Context(
        state=state, timeline=report, brief=brief,
        thin=density.thin_topics(state.claims),
        last_learner_evasive=bool(analysis and analysis.evasive),
        last_learner_struggling=bool(analysis and analysis.struggling),
    )
