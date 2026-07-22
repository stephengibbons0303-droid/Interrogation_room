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

# "Some friends" is not a person. The people signal exists to ask who could be
# gone and spoken to, and a plural with no name attached answers that with
# nobody - it is the vagueness probing is supposed to go after, so counting it
# as a named person told the engine the topic was covered when it was empty.
_UNNAMED_STARTS = ("a ", "an ", "the ", "some ", "my ", "our ", "his ", "her ",
                   "their ", "few ", "a few ", "two ", "three ", "several ",
                   "other ", "another ", "one of ")
_UNNAMED_WORDS = {"friend", "friends", "people", "person", "someone", "somebody",
                  "colleague", "colleagues", "family", "mate", "mates", "group",
                  "others", "everyone", "staff", "waiter", "barman", "barmaid",
                  "them", "they", "us", "we", "guys", "lads"}


def is_named(person: str) -> bool:
    """Does this actually name somebody the police could go and find?"""
    p = (person or "").strip().lower()
    if not p or p in _UNNAMED_WORDS:
        return False
    return not p.startswith(_UNNAMED_STARTS)


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
        """0..1. How much of this could actually be checked by somebody.

        Three things are deliberately NOT scored, each because it comes free and
        so tells us nothing about whether the learner has really said anything:

          * LOCATION. Every claim about an evening carries one, and the timeline
            already tracks them. Counting them made "I was at X, then Y, then Z"
            read as a rich account when it is the bare recital this module
            exists to catch.
          * ACTIVITY. Free text the model fills in on essentially every claim,
            worded differently each time, so distinct-activity count tracks
            claim count almost exactly. Scoring it meant measuring quantity
            twice and calling the result substance - which is how an account
            with no names and no sensory detail in it came out at 1.0.
          * WHETHER A TIME WAS GIVEN. Also near-universal, and it was masking
            the absence of sensory detail by sharing a term with it.

        What is left is what a detective would actually chase: how much they
        said, who they named, and what it was like to be there.
        """
        substance = min(self.claims / 3.0, 1.0)
        named = min(self.people / 2.0, 1.0)
        texture = min(self.sensory / 2.0, 1.0)
        return round(0.30 * substance + 0.35 * named + 0.35 * texture, 3)

    @property
    def thin(self) -> bool:
        """Nobody named and nothing sensory is thin however much was said.

        A gate rather than a weight, because this is the shape the design note
        describes: a block with a couple of entities, no sensory detail and no
        named people. Such a topic can cover an hour of the evening and still
        offer nothing that could later be checked or contradicted.
        """
        if not (self.people or self.sensory):
            return True
        return self.score < THIN

    def missing(self) -> List[str]:
        """What this topic still lacks, in the order it is worth asking for.

        This is the whole payoff: it turns "probe them a bit more" into a
        specific question the detective can put.
        """
        gaps = []
        if not self.people:
            gaps.append("nobody NAMED - who served them, who they were with, who "
                        "would remember them. 'Some friends' is not an answer")
        if not self.sensory:
            gaps.append("nothing seen, heard, smelled or felt - no sensory detail at all")
        if not self.timed:
            gaps.append("nothing anchored to a clock time")
        if not self.places:
            gaps.append("no location given")
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
            if is_named(name):
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


def testable(claims: List[Claim], min_solid: int = 2) -> bool:
    """Is there enough solid ground to be worth attacking?

    Counts what IS substantial rather than demanding that nothing is thin. A
    real interview raises new topics constantly - one run coined five labels in
    fourteen turns - so requiring every topic to be rich would let a single
    fresh mention re-lock reverse chronology, permanently, however much the
    learner had already given. The two uses are deliberately separate:

        thin_topics()  ->  what to press for next
        testable()     ->  is there enough behind us to test them against

    One topic can still qualify on its own if it is strong, because topics are
    free-text labels the model supplies: a run where it reused one label would
    otherwise report a single topic no matter how much was said, and every
    technique behind this gate would silently never fire. That failure - a
    technique that cannot trigger because nothing knows enough to trigger it -
    is the exact thing this whole layer was built to end.
    """
    solid = [d for d in assess(claims).values() if not d.thin]
    if len(solid) >= min_solid:
        return True
    return len(solid) == 1 and solid[0].score >= STRONG
