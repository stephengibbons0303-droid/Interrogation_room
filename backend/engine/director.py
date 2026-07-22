"""The director: who speaks, what they do, how much trouble the learner is in.

Everything here is deterministic and inspectable. The model is left with the one
job it is actually better at - saying the thing well - while the decisions that
need to be consistent, gated and testable are made in Python.
"""
import uuid
from dataclasses import dataclass
from datetime import time as _t
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

# Two claims about one place are only the SAME EPISODE if their spans genuinely
# overlap. People narrate a single stay in consecutive pieces - "I was there from
# five", "between seven and eight I was reading" - and those sit end to end, not
# on top of each other. Without this, describing one evening in segments reads as
# arriving twice, and an account told faithfully gets its teller detained.
_SAME_EPISODE_OVERLAP = 15

# "I left about eight" is the END of a stay, and the extractor reliably encodes
# it as a START - the time is when the leaving happened, after all. Left there,
# every departure gets compared against the arrival of the same stay, and the
# engine reads "arrived at 6.30" then "left about 7.45" as a 75-minute lie about
# arriving. Three of the four contradictions in one playtest were exactly this.
import re as _re

_LEAVING_RX = _re.compile(
    r"\b(left|leave|leaving|departed|finished|walked out|headed (?:off|home)|"
    r"said goodbye|set off|got out)\b", _re.I)

# "I got there about 6 and left about 7.30" states an arrival AND a departure -
# a true span, correctly encoded, which the reclassification below must not
# touch. Only a sentence that leaves WITHOUT arriving has a misleading start.
_ARRIVING_RX = _re.compile(
    r"\b(arriv\w*|got there|got to|got in|went in|went into|reached|turned up|"
    r"showed up|from (?:about|around)?\s*\d|since)\b", _re.I)


def _is_pure_departure(text: str) -> bool:
    t = text or ""
    return bool(_LEAVING_RX.search(t)) and not _ARRIVING_RX.search(t)

# How much of the first telling has to be gone over again before the second one
# counts as given. Measured in ground covered rather than claims re-stated: an
# account of four stretches of the evening might have been built over ten turns,
# and demanding ten re-statements would be a bar nobody could clear.
_RETELLING_DONE = 0.8

# ...but never in fewer than this many turns. A fluent learner can summarise the
# whole evening backwards in one long message, which cleared the bar instantly
# and shut the window before the follow-up had asked a single question - so the
# second telling got measured on one paragraph. Working through it step by step
# is the technique; a complete first answer is not a reason to stop asking.
_RETELLING_MIN_TURNS = 3


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


def place_key(claim: Claim) -> Optional[str]:
    """What the learner said this claim was ABOUT, for comparing like with like.

    Prefers the case location where one was recognised, and otherwise falls back
    to whatever they called it. Without the fallback, everywhere that is not one
    of the four case locations - which in practice is most of an evening - could
    never be compared with anything they said about it later.
    """
    if claim.location:
        return claim.location
    place = (claim.place or "").strip().lower()
    return place or None


# Words that describe rather than identify a place. Left out of the comparison
# so "the cafe" and "a cafe somewhere on the High Street" read as one place.
_PLACE_NOISE = {"the", "a", "an", "in", "at", "on", "near", "by", "to", "of",
                "and", "&", "some", "somewhere", "up", "down", "towards",
                "nearby", "little", "bit"}


def _place_tokens(key: str) -> set:
    out = set()
    for word in key.replace("&", " and ").replace(",", " ").split():
        w = "".join(ch for ch in word.lower() if ch.isalnum())
        if w and w not in _PLACE_NOISE:
            out.add(w)
    return out


def same_place(a: Optional[str], b: Optional[str]) -> bool:
    """Do these two descriptions plausibly name the same place?

    Token overlap, not string equality. One playtest minted nine contradictions
    in a single turn because "Pig & Whistle", "the pub" and "the Pig and
    Whistle pub in Angel Islington" all compared as different places - the
    learner's own re-mentions of one pub read as being in three places at once.
    Erring toward "same" is deliberate: a missed real contradiction costs a
    beat; a manufactured one accuses an honest learner of lying.
    """
    if not a or not b:
        return False
    ta, tb = _place_tokens(a), _place_tokens(b)
    if not ta or not tb:
        return False
    return bool(ta & tb)


def _to_time(minutes: int) -> _t:
    """Minutes-past-midnight to a time, clamped to the evening's last minute.

    Hour and minute both derive from the same clamped value. The old inline
    version clamped only the hour term (`min(end, 23*59) // 60`) while taking the
    minute from the raw value, so an after-midnight bound like 1440 became 23:00
    instead of 23:59 - shrinking or inverting the evidence window.
    """
    m = max(0, min(minutes, 23 * 60 + 59))
    return _t(m // 60, m % 60)


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
    # survives. Dropping a name is forgetting; adding one is remembering. And
    # only actual NAMES play - "work colleagues" one telling and "friends" the
    # next is loose vocabulary, not a different set of people, and it was
    # flagged as a lie until this filter existed.
    first_names = {p.strip().lower() for p in original.people if density.is_named(p)}
    now_names = {p.strip().lower() for p in claim.people if density.is_named(p)}
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
        start_min, end_min = raw.get("start_min"), raw.get("end_min")
        # A departure statement contributes its departure time as the stay's
        # END, and nothing else. Encoded as a start, "I left about 7:45" gets
        # compared against the arrival of the same stay and the gap read as a
        # lie about turning up. And when the sentence carries a second time -
        # "left at 7:45 because I was meeting them at eight" - the pair is not
        # a span of presence anywhere, so keeping it minted phantom overlaps
        # with wherever they really were during those minutes.
        if start_min is not None and _is_pure_departure(raw.get("text", "")):
            start_min, end_min = None, start_min
        claim = Claim(
            id=str(uuid.uuid4()),
            turn_seq=turn_seq,
            text=raw.get("text", "")[:500],
            start_min=start_min,
            end_min=end_min,
            location=raw.get("location"),
            place=raw.get("place"),
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

    # At most ONE self-contradiction per turn. A single vague re-mention once
    # collided with nine prior claims in one pass, and the interview spent four
    # turns hammering the same half-hour. One answer can only move the story
    # once; everything past the first finding is the same movement re-counted.
    minted_self = False

    # The claim the engine deliberately misquoted last turn, if a probe is now
    # being answered. Any "movement" the learner shows on THAT claim this turn is
    # a response to the engine's own planted lie, not spontaneous inconsistency -
    # so it must not mint a contradiction, or acquiescing to the misquote (which
    # resolve_premise records as a miss that "costs NOTHING") would instead cost
    # a wobble and supersede their true statement with the false one. Scoped to
    # the single misquoted claim on the single turn the probe is resolved; if
    # they keep running with the false version later, the probe is closed by then
    # and the ordinary machinery catches it.
    premise_claim_id = None
    if state.premise_open and state.premise_open.get("posed_turn", turn_seq) < turn_seq:
        premise_claim_id = state.premise_open.get("claim_id")

    for cid in new_ids:
        claim = spans.get(cid)
        if claim is None:                      # no time information at all
            continue
        original = state.claim(cid)

        matched = _match_original(state, claim, baseline_turn) if retelling else None
        if matched is not None:
            if original is not None:
                original.restates = matched.id
            if matched.id != premise_claim_id:
                found.extend(_retelling_conflicts(state, claim, matched, turn_seq))

        # Self-contradiction: does this replace something they already said?
        # Skipped for a re-statement, which has just been measured against the
        # first telling - running both would raise one difference twice. The
        # evidence pass below still runs either way: a second telling can move
        # them somewhere they had not walked into before, and that is news.
        for prior in (normalise(state.claims) if matched is None and not minted_self else []):
            if prior.id == cid or prior.turn_seq >= claim.turn_seq:
                continue
            if prior.id == premise_claim_id:   # answering a planted misquote; not a wobble
                continue
            prior_row = state.claim(prior.id)
            if prior_row is None or prior_row.superseded_by:
                continue
            here, there = place_key(claim), place_key(prior)

            # Two places at once. STATED spans only, on the engine's founding
            # rule: never convict on inferred data. "We went to the pub" with no
            # end used to be normalised into a span covering the whole evening,
            # which then "overlapped" every other place they mentioned -
            # consecutive narration read as omnipresence. And the overlap has to
            # be substantial: narrating one journey in touching segments is
            # segmentation, not two places at once.
            if here and there and not same_place(here, there):
                if claim.inferred or prior.inferred:
                    continue
                overlap = min(prior.end_min, claim.end_min) \
                    - max(prior.start_min, claim.start_min)
                if overlap >= _SAME_EPISODE_OVERLAP:
                    minted_self = True
                    prior_row.superseded_by = cid
                    found.append(Contradiction(
                        id=str(uuid.uuid4()), kind="self", turn_seq=turn_seq,
                        detail=f"earlier: '{prior.text}' - now: '{claim.text}'",
                        claim_id=cid, against_claim_id=prior.id,
                        was_vouched=prior_row.vouched_by_chen,
                    ))
                    break
                continue

            # The SAME place, at a different time - and this is the commonest way
            # an account really moves. The check used to require the two claims
            # to name different places, so "I left the cafe about half seven" and
            # "I left the cafe about eight" passed each other without a word.
            # Stated bounds only, never one the timeline filled in, and it has to
            # clear ordinary rounding: refining "about eight" to "ten past" is a
            # learner being careful, not an account changing.
            if not same_place(here, there):
                continue
            raw_now, raw_before = state.claim(cid), prior_row
            if raw_now is None:
                continue
            # Same episode, or merely the next part of one? Overlapping spans
            # are two accounts of the same stretch; consecutive segments are
            # one visit narrated in pieces. EXCEPT when both claims state only
            # the same single bound - two leaving times, or two arrival times,
            # for one place are the same fact twice by construction, and their
            # invented spans sit end to end precisely because the times differ.
            same_field_pair = (
                (raw_now.start_min is None and raw_before.start_min is None)
                or (raw_now.end_min is None and raw_before.end_min is None))
            if not same_field_pair and min(prior.end_min, claim.end_min) \
                    - max(prior.start_min, claim.start_min) < _SAME_EPISODE_OVERLAP:
                continue
            moved, which = 0, ""
            for field, label in (("start_min", "arriving"), ("end_min", "leaving")):
                # An "arriving" comparison is only honest between two claims
                # that are actually about arriving. "I left about 7:45, I was
                # meeting them at eight" carries both bounds, and its start is
                # the departure - set against a real arrival it manufactures a
                # 75-minute lie about turning up.
                if field == "start_min" and (
                        _is_pure_departure(raw_now.text) or _is_pure_departure(raw_before.text)):
                    continue
                a, b = getattr(raw_now, field), getattr(raw_before, field)
                if a is None or b is None:
                    continue                      # supplying a missing bound is not a change
                if abs(a - b) > moved:
                    moved, which = abs(a - b), label
            if moved >= _RETELLING_TIME_SHIFT:
                minted_self = True
                prior_row.superseded_by = cid
                found.append(Contradiction(
                    id=str(uuid.uuid4()), kind="self", turn_seq=turn_seq,
                    detail=(f"{here}, {which}: earlier '{prior.text}' - "
                            f"now '{claim.text}' - {moved} minutes apart"),
                    claim_id=cid, against_claim_id=prior.id,
                    was_vouched=prior_row.vouched_by_chen,
                ))
                break

        # There is deliberately no check here for the account departing from what
        # "really" happened. Under the dealt-account design that was the central
        # test; now the evening is the learner's own invention, so there is no
        # external truth for it to depart from. The only fixed facts are the
        # concealment pair, and conceding one of those is handled above as a
        # breach - on their own words rather than on the engine knowing better.

        # Against the evidence - what makes SUE mechanical rather than
        # hand-written: they commit, and the engine knows what they walked into.
        #
        # Built from STATED bounds only, never the normalised (invented) ones -
        # the same founding rule the self, retelling and breach checks all obey.
        # A single stated bound is a POINT in time, not a span reaching to the
        # edge of the window: "I got to the pub about nine" commits them to being
        # there AT nine, not through the whole evening, so it cannot be walked
        # into evidence covering a later hour. This is SUE's own philosophy - the
        # clash fires on a committed fact - and it means the detective has to
        # extract the second bound before a half-open alibi can be pinned. A fully
        # stated alibi that overlaps the mast still collides, which is the jeopardy
        # the ending is designed around.
        stated_lo = original.start_min if original else None
        stated_hi = original.end_min if original else None
        if stated_lo is None and stated_hi is None:
            continue                              # a place with no committed time
        lo = stated_lo if stated_lo is not None else stated_hi
        hi = stated_hi if stated_hi is not None else stated_lo
        window = (_to_time(lo), _to_time(hi))
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
    if retelling and turn_seq - baseline_turn >= _RETELLING_MIN_TURNS:
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

    # A gap or impossible journey is a standing fact, so it is charged ONCE, when
    # it first appears - not every turn it persists. Ledgered by a stable
    # signature; re-seeing an already-charged artifact adds nothing, which is
    # what stops one unresolved artifact ratcheting pressure every turn (and an
    # unattended mic charging it by wall-clock until the interview self-concludes).
    charged = set(state.charged_artifacts)
    new_gaps = 0
    for g in report.gaps:
        sig = f"gap:{g.start_min}:{g.end_min}"
        if sig not in charged:
            charged.add(sig)
            new_gaps += 1
    if new_gaps:
        gain += min(0.02 * new_gaps, 0.04)
    for m in report.impossible:
        sig = f"imp:{m.a.location}:{m.b.location}:{m.a.end_min}:{m.b.start_min}"
        if sig not in charged:
            charged.add(sig)
            gain += 0.05
    state.charged_artifacts = sorted(charged)

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
    # Probing normally ends when the account is dense enough to be worth attacking
    # - challenging a list of bare assertions is what made the techniques fire into
    # a vacuum. But the patience limit is an UNCONDITIONAL escape, not one more
    # thing gated behind that density: report.complete needs three timed blocks,
    # which a sparse account never reaches, so a learner who cannot produce detail
    # would otherwise be trapped in Probe forever and the interview could never
    # end - a longer interview as punishment for lower proficiency. Past patience
    # they are moved on regardless; Closure then handles the thin account fairly.
    elif stage is Stage.PROBE and (
            (report.complete
             and (state.contradictions or len(state.topics_covered) >= 3)
             and density.testable(state.claims))
            or state.turn >= PROBE_PATIENCE):
        stage = Stage.CHALLENGE
    elif stage is Stage.CHALLENGE and (
            (not state.open_contradictions and state.turn >= 14)
            or state.pressure >= 0.9
            or state.turn >= MAX_TURNS):
        stage = Stage.CLOSURE

    # Absolute backstop: nothing runs past MAX_TURNS in a non-terminal stage.
    # The stage machine advances one step per call, so a run that reaches the cap
    # while still early (an account so thin it never left Free Recall) would
    # otherwise never conclude. Defence in depth against any future gate that
    # could trap a learner mid-interview.
    if state.turn >= MAX_TURNS and stage is not Stage.CLOSURE:
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


# ── the false-premise probe ──────────────────────────────────────────────────

# Twice per interview at most. The probe's power is that it is unforeseeable;
# a third misquote teaches the learner to distrust every summary, which
# poisons the legitimate ones the closure stage depends on.
MAX_PREMISES = 2

# How far the misquote moves a time. Well past the 30-minute rounding allowance
# the engine itself grants, so an attentive learner has something real to catch,
# and unambiguous when they restate the true value.
_PREMISE_SHIFT = 60


def plan_false_premise(state: InterviewState) -> Optional[Dict[str, Any]]:
    """Author a deliberate misstatement of something they actually said.

    The engine knows exactly what was said, so the misquote is generated here -
    deterministically, from the claim store - and the model is only trusted to
    deliver it casually. Two kinds: a stated time moved by an hour, or an event
    relocated to another place from their own account. Only their own claims
    are ever drawn on: the probe misremembers, it never invents.
    """
    if state.premise_open is not None or state.premises_posed >= MAX_PREMISES:
        return None

    live = [c for c in state.claims if not c.superseded_by and not c.restates]
    # Prefer claims a couple of turns old: misquoting what they said seconds
    # ago is not a memory test, it is a hearing test.
    seasoned = [c for c in live if c.turn_seq <= state.turn - 2] or live

    options: List[Dict[str, Any]] = []
    all_places = [c.place for c in live if c.place]

    for c in seasoned:
        where = c.place or (f"the {c.location}" if c.location else None)

        stated = c.end_min if c.end_min is not None else c.start_min
        if stated is not None:
            false_t = stated - _PREMISE_SHIFT
            if false_t < 17 * 60:
                false_t = stated + _PREMISE_SHIFT
            verb = "left" if c.end_min is not None else "got there"
            spot = f" {where}" if where else ""
            options.append({
                "claim_id": c.id, "kind": "time", "true_min": stated,
                "quote": c.text,
                "false": f"you {verb}{spot} at about {_fmt(false_t)}",
            })

        if c.place:
            elsewhere = next((p for p in all_places
                              if not same_place(p, c.place)), None)
            if elsewhere:
                options.append({
                    "claim_id": c.id, "kind": "place", "true_min": None,
                    "quote": c.text,
                    "false": f"that this was at {elsewhere}",
                })

    if not options:
        return None
    return options[state.premises_posed % len(options)]


def resolve_premise(state: InterviewState, corrected: Optional[bool],
                    fresh_claims: List[Claim]) -> Optional[bool]:
    """Settle a pending probe against the learner's reply.

    `corrected` is the model's read of whether they pushed back. The fallback
    is mechanical: restating the true time is a correction whether or not the
    model noticed. Both only ever argue TOWARD caught - a miss is recorded, and
    deliberately costs nothing.
    """
    p = state.premise_open
    if not p or p.get("posed_turn") == state.turn:
        return None                       # their answer has not arrived yet

    caught = corrected is True
    if not caught and p.get("true_min") is not None:
        for c in fresh_claims:
            for bound in (c.start_min, c.end_min):
                if bound is not None and abs(bound - p["true_min"]) <= 15:
                    caught = True

    state.premise_open = None
    if caught:
        state.premises_caught += 1
        # The CBCA credit: spontaneous correction marks genuine recall.
        state.exculpation = min(1.0, state.exculpation + 0.08)
    else:
        state.premises_missed += 1
    return caught


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
        false_premise=plan_false_premise(state),
        last_learner_evasive=bool(analysis and analysis.evasive),
        last_learner_struggling=bool(analysis and analysis.struggling),
    )
