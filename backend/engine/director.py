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
from engine import tactics as tac
from engine.analysis import TurnAnalysis
from engine.state import (CHEN_ARC, STAGE_ORDER, ChenStance, Claim,
                          Contradiction, InterviewState, Outcome, Stage)
from engine.timeline import TimelineReport, build as build_timeline

LEAD = "Reynolds"
SECOND = "Chen"

# The researched division of labour: the lead takes roughly three turns in four.
# Used only as a nudge - triggers below take precedence, because the document is
# clear that hand-offs happen for reasons, not on a quota.
LEAD_SHARE_TARGET = 0.75

MAX_TURNS = 40


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


def ingest(state: InterviewState, extraction: Extraction, analysis: TurnAnalysis,
           brief: Optional[Brief], turn_seq: int) -> List[Contradiction]:
    """Fold a learner turn into state and return any NEW contradictions."""
    found: List[Contradiction] = []

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
            vouched_by_chen=extraction.chen_vouched_claim,
        )

        # Self-contradiction: does this replace something they already said?
        if claim.has_window:
            for prior in state.live_claims:
                if not prior.has_window or prior.id == claim.id:
                    continue
                overlaps = (prior.start_min < claim.end_min
                            and claim.start_min < prior.end_min)
                if overlaps and prior.location and claim.location \
                        and prior.location != claim.location:
                    prior.superseded_by = claim.id
                    found.append(Contradiction(
                        id=str(uuid.uuid4()), kind="self", turn_seq=turn_seq,
                        detail=f"earlier: '{prior.text}' — now: '{claim.text}'",
                        claim_id=claim.id, against_claim_id=prior.id,
                        was_vouched=prior.vouched_by_chen,
                    ))

        # Against the brief - the ground truth the learner was dealt.
        if brief:
            for fact in brief.committed_blocks():
                if not claim.has_window or not fact.location or not claim.location:
                    continue
                f_start = fact.window[0].hour * 60 + fact.window[0].minute
                f_end = fact.window[1].hour * 60 + fact.window[1].minute
                if f_start < claim.end_min and claim.start_min < f_end \
                        and fact.location != claim.location:
                    found.append(Contradiction(
                        id=str(uuid.uuid4()), kind="brief", turn_seq=turn_seq,
                        detail=f"account departs from what actually happened: {fact.text}",
                        claim_id=claim.id,
                    ))

        # Against the evidence - this is what makes SUE mechanical rather than
        # hand-written: the learner commits, and the engine knows what they hit.
        if claim.has_window:
            from datetime import time as _t
            window = (_t(claim.start_min // 60 % 24, claim.start_min % 60),
                      _t(min(claim.end_min, 23 * 60 + 59) // 60 % 24, claim.end_min % 60))
            for ev in case.evidence_for(window, claim.location):
                if ev.id in state.disclosed:
                    continue
                if any(c.evidence_id == ev.id for c in state.contradictions):
                    continue
                found.append(Contradiction(
                    id=str(uuid.uuid4()), kind="evidence", turn_seq=turn_seq,
                    detail=f"'{claim.text}' does not sit with: {ev.fact}",
                    claim_id=claim.id, evidence_id=ev.id,
                ))

        state.claims.append(claim)

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
# A "brief" contradiction scores ZERO. It means the account departs from what
# really happened - but on a concealing brief that IS the game: the learner is
# supposed to be hiding something, and the detectives cannot see the brief. Only
# the engine knows, and it uses that knowledge to decide the ending, not to
# punish the lie as it is being told. Scoring it made pressure hit the ceiling in
# seven turns purely for playing the part properly.
_PRESSURE_FOR = {"self": 0.10, "brief": 0.0, "evidence": 0.15}

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
    elif stage is Stage.PROBE and report.complete and (
            state.contradictions or len(state.topics_covered) >= 3):
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

    Judged on what the detectives actually got, not on what the engine knows.
    A learner who conceals successfully and is never caught out walks - which is
    the correct result: they beat the interview.
    """
    if Stage(state.stage) is not Stage.CLOSURE:
        return None

    # Evidence actually put to them, and not explained away.
    caught = [c for c in state.contradictions if c.kind == "evidence" and c.raised]
    wobbled = [c for c in state.contradictions if c.kind == "self"]

    if state.pressure >= 0.6 and caught:
        return Outcome.DETAINED.value
    if state.pressure >= 0.3 or caught or len(wobbled) >= 2:
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
        last_learner_evasive=bool(analysis and analysis.evasive),
        last_learner_struggling=bool(analysis and analysis.struggling),
    )
