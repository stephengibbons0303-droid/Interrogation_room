"""The tactical layer: interview techniques with real trigger conditions.

The taxonomy describes two layers - a structural one that picks the framework
and a tactical one that "selects micro-techniques based on conversation state".
Previously only the structural half existed, and even that ran on a turn counter.
Techniques were six bullets in a prompt under "rotate these naturally", so
reverse chronology could never fire after a timeline was given: nothing knew.

Here each technique declares which PEACE stage permits it, what must be true of
the interview before it may be used, and how long it must wait before repeating.
The director filters on all three, then offers the survivors to the model.
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from scenario.briefs import Brief
from engine import density
from engine.density import TopicDensity
from engine.state import ChenStance, InterviewState, Stage
from engine.timeline import TimelineReport

EITHER = "either"


@dataclass
class Context:
    """Everything a precondition is allowed to look at."""
    state: InterviewState
    timeline: TimelineReport
    brief: Optional[Brief] = None
    # Topics the learner has raised but not yet said anything substantial about,
    # thinnest first. What the probe stage exists to empty.
    thin: List[TopicDensity] = field(default_factory=list)
    last_learner_evasive: bool = False
    last_learner_struggling: bool = False


@dataclass
class Tactic:
    id: str
    owner: str                                  # "Reynolds" | "Chen" | EITHER
    stages: List[Stage]
    instruction: str                            # what the model is told to do
    precondition: Callable[[Context], bool] = lambda c: True
    cooldown: int = 0                           # turns before it may repeat
    weight: float = 1.0                         # tie-break priority
    two_voices: bool = False                    # emits an aside, not a single line

    def available(self, ctx: Context, speaker: str) -> bool:
        if Stage(ctx.state.stage) not in self.stages:
            return False
        if self.owner != EITHER and self.owner != speaker:
            return False
        if ctx.state.on_cooldown(self.id):
            return False
        return self.precondition(ctx)


# ── preconditions ────────────────────────────────────────────────────────────

def _timeline_ready(c: Context) -> bool:
    """An account covering enough of the evening exists. The gate the old build
    never had - though covering the evening is not the same as being worth
    attacking, which is what _account_testable adds."""
    return c.timeline.complete


def _account_testable(c: Context) -> bool:
    """Enough SUBSTANCE to be worth attacking, not merely enough time covered.

    An account can span the whole evening and still be a row of bare assertions.
    Running that backwards proves nothing about anybody - the delta between two
    tellings is only meaningful when there was something in the first one.

    Deliberately the same rule the probe stage exits on, rather than a second one
    that happens to look similar: "worth attacking" should not mean two different
    things depending on who is asking.
    """
    return c.timeline.complete and density.testable(c.state.claims)


def _account_thin(c: Context) -> bool:
    """Something they have raised is still empty, and worth pressing."""
    return bool(c.thin)


def _mid_retelling(c: Context) -> bool:
    return c.state.retelling_active


def _may_ask_retelling(c: Context) -> bool:
    """May a detective ask for the account again? See InterviewState."""
    return c.state.may_ask_retelling


def _has_open_contradiction(c: Context) -> bool:
    return bool(c.state.open_contradictions)


def _has_undisclosed_clash(c: Context) -> bool:
    """A committed claim walks into evidence that has not been put yet."""
    return any(x.kind == "evidence" and not x.raised
               for x in c.state.contradictions)


def _learner_needs_support(c: Context) -> bool:
    """Back off rather than escalate - a learner losing the thread is not evasion."""
    return c.last_learner_struggling or c.state.nonresponsive_streak >= 2


def _chen_is_working_them(c: Context) -> bool:
    return ChenStance(c.state.chen_stance) in (
        ChenStance.IDENTIFYING, ChenStance.MINIMISING)


def _aside_worthwhile(c: Context) -> bool:
    """Asides are strong; they become wallpaper if used as filler.

    Requires something concrete to confer about, a per-stage cap, and - the
    pedagogical guard - that the learner is not currently struggling, because
    overheard dialogue is harder listening than being addressed directly.
    """
    if c.state.asides_this_stage >= 2:
        return False
    if _learner_needs_support(c):
        return False
    return bool(c.state.open_contradictions
                or c.timeline.gaps
                or c.timeline.impossible
                or c.last_learner_evasive)


# ── the registry ─────────────────────────────────────────────────────────────

_ALL: List[Tactic] = [

    # ENGAGE — rapport and ground rules. PEACE puts these first for a reason:
    # they train the interviewee to give elaborated answers.
    Tactic("engage_rapport", EITHER, [Stage.ENGAGE],
           "Open neutrally. Get their name and settle them. Do not touch the case yet.",
           weight=2.0),
    Tactic("explain_ground_rules", "Reynolds", [Stage.ENGAGE],
           "State the procedure and the caution. Tell them plainly: if you do not "
           "understand a question, say so; do not guess; correct me if I summarise you wrongly.",
           cooldown=99, weight=1.8),

    # FREE RECALL — one open question, then let them talk.
    Tactic("free_recall", EITHER, [Stage.FREE_RECALL],
           "Ask ONE open question inviting the whole account of Thursday evening, "
           "then stop. Do not interrupt, do not sub-divide it, ask nothing else.",
           cooldown=4, weight=3.0),
    Tactic("report_everything", "Chen", [Stage.FREE_RECALL, Stage.PROBE],
           "Tell them to include everything, even things that seem small or irrelevant, "
           "because small details often bring back bigger ones. Add: do not guess, and "
           "say so if you do not know.",
           cooldown=6),

    # PROBE — turn the account into checkable facts.
    Tactic("funnel_probe", EITHER, [Stage.PROBE],
           "Take ONE topic they have raised and funnel it: start with Tell me / Explain / "
           "Describe, then narrow with who, what, when, where, how. One question only this turn.",
           weight=2.0),
    Tactic("context_reinstatement", "Chen", [Stage.PROBE],
           "Cognitive-interview context reinstatement. Ask them to put themselves back "
           "there - what they could see, hear, how cold it was, what they were thinking - "
           "before answering.",
           cooldown=8),
    Tactic("anchor_commitment", EITHER, [Stage.PROBE],
           "Pin them to something specific and repeat it back so it is on the record: an "
           "exact time, a route, who was present. Make the commitment explicit.",
           cooldown=3, weight=1.5),
    Tactic("detail_expansion", "Chen", [Stage.PROBE],
           "Pick one small detail they mentioned and open it out - what were they watching, "
           "who served them, what was the weather doing.",
           cooldown=4),

    # Directed probing. funnel_probe picks a topic; this one is aimed at the
    # specific hole the engine has measured, which is what turns "press them a
    # bit more" into a question worth asking. Outranks funnel_probe so that
    # anything empty gets filled before the account is treated as testable.
    Tactic("press_thin_detail", EITHER, [Stage.PROBE],
           "One part of their account is still empty. Press it for the exact thing it is "
           "missing - who else was there, what the place was like, what time it was. ONE "
           "question, aimed squarely at the gap you are told about.",
           precondition=_account_thin, cooldown=2, weight=2.6),
    Tactic("topic_switch", "Reynolds", [Stage.PROBE, Stage.CHALLENGE],
           "Abruptly change topic away from what you were pursuing, then come back to it "
           "later. Rehearsed accounts survive linear questioning; they do not survive this.",
           precondition=lambda c: len(c.state.topics_covered) >= 2,
           cooldown=6),
    Tactic("unanticipated_question", "Reynolds", [Stage.PROBE, Stage.CHALLENGE],
           "Ask something they cannot have prepared: what was on their left as they walked "
           "in, what the staff looked like, which way the queue faced.",
           precondition=_timeline_ready, cooldown=5),

    # The technique this whole rebuild was prompted by. It needs an account with
    # something IN it, not merely one that covers the evening: the jeopardy is
    # the difference between the first telling and the second, and a bare list
    # of assertions cannot differ from itself in any way worth noticing.
    Tactic("reverse_chronology", EITHER, [Stage.PROBE, Stage.CHALLENGE],
           "Ask them to tell the evening again BACKWARDS - from the end of the night to "
           "the start. Say plainly that you want it in reverse order. Then let them work. "
           "Rehearsed accounts are built forwards and come apart when run backwards.",
           precondition=lambda c: _account_testable(c) and _may_ask_retelling(c),
           cooldown=12, weight=2.5),

    # The other way of asking for it twice. Reverse order is the harder version;
    # this one is less obviously a test, which is its advantage.
    Tactic("retell_from_point", EITHER, [Stage.PROBE, Stage.CHALLENGE],
           "Pick one fixed moment they have already described and ask them to work "
           "OUTWARD from it - what came immediately before, what came immediately after. "
           "Do not signal that you are checking anything.",
           precondition=lambda c: _account_testable(c) and _may_ask_retelling(c),
           cooldown=10, weight=2.3),

    # Once they are re-telling, keep them at it. Without this the director picks
    # a fresh tactic on the next turn and the second telling gets exactly one
    # turn - not enough of it to compare against anything.
    Tactic("retelling_followup", EITHER, [Stage.PROBE, Stage.CHALLENGE],
           "They are part-way through giving the account again. Keep them going: ask for "
           "the next step, in the order you asked for. Do NOT remind them what they said "
           "the first time, do not fill anything in for them, and do not help.",
           precondition=_mid_retelling, weight=3.4),

    # CHALLENGE — only after both agendas are exhausted.
    Tactic("challenge_contradiction", EITHER, [Stage.CHALLENGE],
           "Put ONE inconsistency to them, neutrally, as an observation rather than an "
           "accusation: you said X, now you say Y, help me understand. Then wait.",
           precondition=_has_open_contradiction, weight=3.0),
    Tactic("sue_disclose", "Reynolds", [Stage.CHALLENGE],
           "Strategic Use of Evidence. Introduce the evidence you have been given at the "
           "framing level specified - no more precise than stated. Let it land against what "
           "they have already committed to.",
           precondition=_has_undisclosed_clash, weight=2.8),
    Tactic("bait_question", "Reynolds", [Stage.CHALLENGE],
           "Ask whether there is any reason a particular thing might turn up - footage, a "
           "print, a record - without confirming that it exists.",
           precondition=_timeline_ready, cooldown=8),
    Tactic("strategic_silence", "Reynolds", [Stage.PROBE, Stage.CHALLENGE],
           "Put one short, heavy question or observation and then stop dead. No follow-up, "
           "no softening. Two sentences at most.",
           cooldown=7),
    Tactic("minimisation", "Chen", [Stage.CHALLENGE],
           "Offer them a way to say it that costs them nothing: the pressure they were "
           "under, how anyone might have done the same, how understandable it would be. "
           "Warm, sympathetic, and entirely deliberate.",
           precondition=_chen_is_working_them, cooldown=5, weight=2.2),

    # Available in any stage.
    Tactic("rapport_repair", "Chen", [Stage.ENGAGE, Stage.FREE_RECALL,
                                      Stage.PROBE, Stage.CHALLENGE],
           "They are floundering. Slow everything down, take the pressure off, reassure "
           "them, and ask something small and easy that they can answer.",
           precondition=_learner_needs_support, weight=4.0),

    # The two-hander. Emits two utterances - see director.
    Tactic("detective_aside", EITHER, [Stage.PROBE, Stage.CHALLENGE],
           "Turn to your colleague and discuss the subject in front of them, as though "
           "they were not there. Two short exchanges. They are talked about, not to.",
           precondition=_aside_worthwhile, cooldown=6, weight=2.4, two_voices=True),

    # CLOSURE.
    Tactic("closure_summary", EITHER, [Stage.CLOSURE],
           "Summarise their account back in their own words, invite corrections, and tell "
           "them what happens next.",
           weight=3.0),
]

REGISTRY: Dict[str, Tactic] = {t.id: t for t in _ALL}


def available(ctx: Context, speaker: str) -> List[Tactic]:
    """Tactics this speaker may legally use right now, best first."""
    ok = [t for t in _ALL if t.available(ctx, speaker)]
    return sorted(ok, key=lambda t: t.weight, reverse=True)


def get(tactic_id: str) -> Optional[Tactic]:
    return REGISTRY.get(tactic_id)
