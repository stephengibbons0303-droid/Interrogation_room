"""Detail density: how much substance the account actually has, topic by topic.

Once the learner's own account is the ground truth, the middle of the interview
stops being about catching anyone and becomes about manufacturing the material to
test later. The taxonomy is explicit that funnel questioning exists to produce
"checkable facts and provable lies" - the more detail obtained, the more
verifiable or falsifiable the account becomes.

That is only actionable if the engine can tell a thin topic from a rich one. It
can: a topic with two entities, nothing sensory and nobody named is thin, and
worth pressing. So probing runs until the account is worth attacking, rather than
until a turn counter says so, and the technique that needs it most - reverse
chronology - stays locked until there is something to reverse.

THE RULE THIS MODULE MUST NOT BREAK: density never raises pressure. A learner
whose account is thin because they are short of vocabulary is doing precisely
what the app exists to make them do. Thinness directs the next question; it is
never evidence of anything.

Pure functions over claims - no LLM, no I/O, so it is unit-testable.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from engine.analysis import analyse
from engine.state import Claim

# Below this a topic is not yet worth testing. Deliberately forgiving: the point
# is to catch a topic with nothing in it, not to demand a novel.
THIN = 0.45

# A single topic this rich is an account in its own right - see testable().
STRONG = 0.75

# No topic label at all. Claims arrive untagged when the model does not name the
# topic, and they should still count for something rather than vanish.
UNTAGGED = "the evening"


@dataclass
class TopicDensity:
    """What the learner has actually given about one topic."""
    topic: str
    claims: int = 0
    people: int = 0                      # distinct names
    places: int = 0                      # distinct locations
    activities: int = 0                  # distinct things done
    sensory: int = 0                     # saw / heard / cold / loud ...
    timed: int = 0                       # claims anchored to a clock time

    @property
    def score(self) -> float:
        """0..1. Quantity of detail first, as the research orders it, then the
        checkable half - who was there and what was done - then grounding.

        Locations are deliberately NOT scored. Every claim about the evening
        comes with one for free, the timeline already tracks them, and counting
        them made "I was at X, then Y, then Z" read as a rich account when it is
        the exact bare recital this module exists to detect.
        """
        substance = min(self.claims / 3.0, 1.0)
        who_what = min((self.people + self.activities) / 3.0, 1.0)
        texture = min((self.sensory + self.timed) / 3.0, 1.0)
        return round(0.35 * substance + 0.45 * who_what + 0.20 * texture, 3)

    @property
    def thin(self) -> bool:
        """Nobody named and nothing done is thin whatever else it has.

        A gate rather than a weight, because this is the shape the design note
        describes: a block with a couple of entities, no sensory detail and no
        named people. Such a topic can cover an hour of the evening and still
        offer nothing that could later be checked, corroborated or contradicted.
        """
        if not (self.people or self.activities):
            return True
        return self.score < THIN

    def missing(self) -> List[str]:
        """What this topic still lacks, in the order it is worth asking for.

        This is the whole payoff: it turns "probe them a bit more" into a
        specific question the detective can put.
        """
        gaps = []
        if not self.people:
            gaps.append("nobody named - who else was there, who served them, who saw them")
        if not self.timed:
            gaps.append("nothing anchored to a clock time")
        if not self.places:
            gaps.append("no location given")
        if not self.sensory:
            gaps.append("nothing seen, heard or felt - no sensory detail at all")
        if self.claims < 2:
            gaps.append("barely touched - one statement and nothing more")
        return gaps


def assess(claims: List[Claim]) -> Dict[str, TopicDensity]:
    """Measure every topic the learner has said anything about.

    Two kinds of claim are excluded. A superseded one is a statement they have
    since replaced, so it is not detail the account still carries. A re-statement
    is ground already counted the first time round - letting a second telling
    inflate density would mean an account got richer by being repeated, and the
    probe stage would stand down exactly when the learner had added nothing.
    """
    out: Dict[str, TopicDensity] = {}
    seen_people: Dict[str, set] = {}
    seen_places: Dict[str, set] = {}
    seen_activities: Dict[str, set] = {}

    for claim in claims:
        if claim.superseded_by is not None or claim.restates is not None:
            continue
        topic = (claim.topic or UNTAGGED).strip().lower() or UNTAGGED
        d = out.setdefault(topic, TopicDensity(topic=topic))
        seen_people.setdefault(topic, set())
        seen_places.setdefault(topic, set())
        seen_activities.setdefault(topic, set())

        d.claims += 1
        # Counted distinctly: repeating the same name in five claims is one
        # person, not five, and treating it as five would call a thin topic rich.
        for name in claim.people:
            if name and name.strip():
                seen_people[topic].add(name.strip().lower())
        if claim.location:
            seen_places[topic].add(claim.location.strip().lower())
        if claim.activity:
            seen_activities[topic].add(claim.activity.strip().lower())
        if claim.start_min is not None or claim.end_min is not None:
            d.timed += 1
        d.sensory += analyse(claim.text or "").sensory

    for topic, d in out.items():
        d.people = len(seen_people[topic])
        d.places = len(seen_places[topic])
        d.activities = len(seen_activities[topic])
    return out


def thin_topics(claims: List[Claim]) -> List[TopicDensity]:
    """Every topic not yet worth testing, thinnest first."""
    return sorted([d for d in assess(claims).values() if d.thin],
                  key=lambda d: d.score)


def thinnest(claims: List[Claim]) -> Optional[TopicDensity]:
    """The topic most worth pressing next, or None if the account is solid."""
    thin = thin_topics(claims)
    return thin[0] if thin else None


def testable(claims: List[Claim], min_topics: int = 2) -> bool:
    """Is the account rich enough to be worth attacking?

    Wants a few topics AND none of them thin. The second half is the point: an
    account can cover the whole evening and still be a list of assertions with
    nothing in it, and running that backwards proves nothing about anyone.

    The topic count alone cannot be a hard gate, though. Topics are free-text
    labels supplied by the model, so a run where it reuses one label throughout
    would report a single topic no matter how much the learner said - and every
    technique behind this gate, reverse chronology included, would silently
    never fire. That is the exact failure this whole layer was built to end:
    a technique that could not trigger because nothing knew enough to trigger
    it. So one topic still qualifies, provided it is substantial on its own.
    """
    measured = assess(claims)
    if not measured or any(d.thin for d in measured.values()):
        return False
    if len(measured) >= min_topics:
        return True
    return max(d.score for d in measured.values()) >= STRONG
