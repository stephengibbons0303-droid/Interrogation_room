"""InterviewState - everything the engine reasons over, in one serialisable place.

Persisted as JSON on Interview.engine_state, so an interview can be resumed with
its pressure, its half-finished timeline and Chen's stance exactly where the
learner left them.

Times are stored as minutes past midnight rather than `time` objects: they
survive a JSON round-trip unchanged and arithmetic on them is trivial.
"""
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Stage(str, Enum):
    """PEACE, minus the phases that happen outside the room.

    This is the *structural* layer and it governs which tactics are permitted.
    It is deliberately separate from pressure, which governs tone - conflating
    the two is what made the old build escalate on a timer.
    """
    ENGAGE = "engage"
    FREE_RECALL = "free_recall"
    PROBE = "probe"
    CHALLENGE = "challenge"
    CLOSURE = "closure"


STAGE_ORDER = [Stage.ENGAGE, Stage.FREE_RECALL, Stage.PROBE,
               Stage.CHALLENGE, Stage.CLOSURE]


class ChenStance(str, Enum):
    """Chen's arc. She is the trap, and the trap has to be built in stages.

    Everything up to MINIMISING reads as kindness. STING is where it is revealed
    to have been strategy, and it must be earned - see director.
    """
    NEUTRAL = "neutral"
    RAPPORT = "rapport"
    ADVOCATE = "advocate"
    IDENTIFYING = "identifying"
    MINIMISING = "minimising"
    STING = "sting"


CHEN_ARC = [ChenStance.NEUTRAL, ChenStance.RAPPORT, ChenStance.ADVOCATE,
            ChenStance.IDENTIFYING, ChenStance.MINIMISING]


class Outcome(str, Enum):
    RELEASED = "released"
    UNDER_INVESTIGATION = "under_investigation"
    DETAINED = "detained"


@dataclass
class Claim:
    """Something the learner committed to."""
    id: str
    turn_seq: int
    text: str
    start_min: Optional[int] = None       # minutes past midnight
    end_min: Optional[int] = None
    location: Optional[str] = None
    activity: Optional[str] = None
    people: List[str] = field(default_factory=list)
    # Which topic was live when they said it. Carried on the claim rather than
    # derived later, because detail density is measured per topic and the only
    # moment the topic is known for certain is the turn it was extracted on.
    topic: Optional[str] = None
    # Set when a later claim replaces this one - that replacement is itself the
    # contradiction, so the original is kept rather than overwritten.
    superseded_by: Optional[str] = None
    # True when Chen explicitly encouraged the learner to commit to this. The
    # sting fires only on one of these.
    vouched_by_chen: bool = False

    # Set on the copies produced by timeline.normalised() when a bound had to be
    # invented because speech only gave one. Such a span is good enough to
    # measure coverage, but not to accuse someone of contradicting themselves.
    inferred: bool = False

    @property
    def has_window(self) -> bool:
        return self.start_min is not None and self.end_min is not None


@dataclass
class Contradiction:
    id: str
    # self     - their account moved
    # evidence - their account walked into something the police hold
    # breach   - they conceded the very thing they were told to conceal. Their
    #            own words, so unlike the other two the detectives can act on it
    #            without needing to disbelieve anybody.
    kind: str
    turn_seq: int
    detail: str
    claim_id: Optional[str] = None
    against_claim_id: Optional[str] = None
    evidence_id: Optional[str] = None
    raised: bool = False                  # has a detective put it to them yet
    was_vouched: bool = False             # did Chen vouch for the broken claim


@dataclass
class InterviewState:
    brief_id: str = ""
    stage: str = Stage.ENGAGE.value
    turn: int = 0

    # Jeopardy. Pressure rises on story failures and deliberate evasion only -
    # never on language quality. Exculpation is its counterweight.
    pressure: float = 0.0
    exculpation: float = 0.0

    claims: List[Claim] = field(default_factory=list)
    contradictions: List[Contradiction] = field(default_factory=list)

    # evidence_id -> highest framing level reached (vague | moderate | precise)
    disclosed: Dict[str, str] = field(default_factory=dict)

    topics_covered: List[str] = field(default_factory=list)
    current_topic: Optional[str] = None

    # tactic id -> turns remaining before it may be used again
    cooldowns: Dict[str, int] = field(default_factory=dict)

    chen_stance: str = ChenStance.NEUTRAL.value
    speaker_counts: Dict[str, int] = field(default_factory=lambda: {"Reynolds": 0, "Chen": 0})
    asides_this_stage: int = 0

    # Kept as first-class fields rather than stashed in `cooldowns`, which
    # tick_cooldowns() decrements and prunes every turn.
    last_speaker: Optional[str] = None
    consecutive_speaker: int = 0

    # Consecutive turns where the learner did not address the question. Used to
    # back off rather than escalate: a learner losing the thread of overheard
    # dialogue is a comprehension problem, not evasion.
    nonresponsive_streak: int = 0

    # Turns of DELIBERATE dodging - refusals, and fluent deflection from someone
    # plainly not struggling. Counted separately from pressure because the ending
    # needs to tell "would not talk" from "could not", and pressure cannot: it
    # also rises from evidence the learner had no way to avoid walking into.
    evasions: int = 0

    outcome: Optional[str] = None

    # ── derived helpers ──────────────────────────────────────────────────────

    @property
    def live_claims(self) -> List[Claim]:
        return [c for c in self.claims if c.superseded_by is None]

    @property
    def open_contradictions(self) -> List[Contradiction]:
        return [c for c in self.contradictions if not c.raised]

    def claim(self, claim_id: str) -> Optional[Claim]:
        return next((c for c in self.claims if c.id == claim_id), None)

    def vouched_claims(self) -> List[Claim]:
        return [c for c in self.claims if c.vouched_by_chen]

    def tick_cooldowns(self) -> None:
        self.cooldowns = {k: v - 1 for k, v in self.cooldowns.items() if v - 1 > 0}

    def on_cooldown(self, tactic_id: str) -> bool:
        return self.cooldowns.get(tactic_id, 0) > 0

    def lead_share(self) -> float:
        total = sum(self.speaker_counts.values())
        return (self.speaker_counts.get("Reynolds", 0) / total) if total else 0.0

    # ── persistence ──────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "InterviewState":
        if not data:
            return cls()
        data = dict(data)
        data["claims"] = [Claim(**c) for c in data.get("claims", [])]
        data["contradictions"] = [Contradiction(**c) for c in data.get("contradictions", [])]
        known = {f for f in cls.__dataclass_fields__}          # tolerate old rows
        return cls(**{k: v for k, v in data.items() if k in known})
