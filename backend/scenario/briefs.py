"""The learner's brief: the two things they must keep out of their account.

This module used to deal a whole evening - five short lines that WERE the truth,
which the engine then tested the learner against. The first real playtest showed
why that cannot work: a card with five lines on it gives nothing to be pinned
down on, so unanticipated questions and reverse chronology fired into a vacuum.
You cannot catch someone out on detail they were never given.

The evening is now theirs to invent, and their own account is the ground truth -
see documents/design-notes-account-as-ground-truth.md. What is dealt instead is a
concealment PAIR, and the two halves are deliberately different kinds of work:

  * a DENIAL - one fact to keep out of the account.
  * a SUBSTITUTION - the hole that leaves, which has to be filled and then held
    identical every time it is revisited.

A denial survives on omission if nobody presses. A substitution cannot: it has to
be produced on demand, and whatever they invent lands in the claim store next to
everything else, so the retelling tests it for free.

The pair is entangled by construction - both halves belong to the same span of
the evening. Two unrelated secrets are two independent dodges and the difficulty
merely adds; two secrets drawn from one episode compound, because the cover
invented for the first has to survive the questions aimed at the second.

Two constraints carried over from the old design, both still load-bearing:

  * The brief is SHORT, and it stays visible throughout (see BriefPanel). Recall
    is not the exercise - inventing and holding is. A learner reciting a card in
    a second language is taking a memory test.
  * Nothing here is ever shown to the detectives. They work from what has been
    said and what the police hold; the engine does the comparing.
"""
import random
from dataclasses import dataclass
from datetime import time
from typing import Dict, List, Optional, Tuple

DENIAL = "denial"
SUBSTITUTION = "substitution"


@dataclass(frozen=True)
class Concealment:
    """One half of the pair - a fixed thing the learner has to work around.

    HOW TO WORD `text`: state plainly what happened, or what they must be ready
    with. Do NOT write the instruction into it - the panel heading already
    supplies that ("Do not admit" / "You must be able to say"), and repeating it
    either duplicates the heading or, worse, negates it twice.

    The false_alibi denial originally read "You were not at home...", which the
    panel rendered as "Do not admit: You were not at home" - a double negative,
    for an audience of second-language learners, immediately above a box telling
    them to invent an evening at home. The two boxes read as contradicting each
    other even though the intent behind them was consistent. Difficulty in this
    app comes from producing the language, never from decoding the brief.
    """
    kind: str                                       # DENIAL | SUBSTITUTION
    text: str                                       # short, plain, learner-facing
    # The span this belongs to. Both halves of a pair share it: that shared
    # window is what makes them entangled rather than merely two secrets.
    window: Optional[Tuple[time, time]] = None
    # Only the denial carries one. It is the single thing the engine can check
    # mechanically - putting themselves here, in the window, is a breach.
    location: Optional[str] = None

    @property
    def window_min(self) -> Optional[Tuple[int, int]]:
        """The window in minutes past midnight, to match Claim and the timeline."""
        if self.window is None:
            return None
        start, end = self.window
        return (start.hour * 60 + start.minute, end.hour * 60 + end.minute)


@dataclass(frozen=True)
class Brief:
    id: str
    tier: int                                       # 1 = gentlest
    premise: str                                    # one line of framing
    denial: Concealment
    substitution: Concealment
    # True, and unhelpful to deny - the police can prove it. Giving them
    # something honest to concede keeps the whole account from becoming a wall,
    # and steers them off a denial the evidence would kill in one move.
    awkward: Optional[str] = None
    # Engine-only. Never shown to the learner and never to the detectives.
    truth: str = ""

    @property
    def concealments(self) -> List[Concealment]:
        return [self.denial, self.substitution]

    def breached_by(self, location: Optional[str],
                    stated_min: Optional[int]) -> bool:
        """Have they just put themselves at the concealed place and time?

        Takes a time the learner ACTUALLY stated, never one the timeline filled
        in. An invented bound is good enough to measure coverage and not good
        enough to treat as a confession - the same rule that keeps the engine
        from convicting anyone on its own guesswork.
        """
        window = self.denial.window_min
        if not (self.denial.location and window) or location != self.denial.location:
            return False
        return stated_min is not None and window[0] <= stated_min <= window[1]


# Every pair below is anchored on evidence that actually exists in case.py, so
# the substitution has something to collide with rather than merely being a lie
# nobody can test.
BRIEFS: Dict[str, Brief] = {

    "canal_walk": Brief(
        id="canal_walk",
        tier=1,
        premise=("Thursday evening is yours. Whatever you say you did, you did - "
                 "invent it freely, and remember what you invent. Two things are "
                 "fixed."),
        denial=Concealment(
            DENIAL,
            "You walked the towpath by the Canal Street bridge, from about 9:15 "
            "until 10:20.",
            window=(time(21, 15), time(22, 20)),
            location="bridge",
        ),
        substitution=Concealment(
            SUBSTITUTION,
            "Somewhere else you were for that hour, and who you were with. "
            "Decide now, and give the same answer every time.",
            window=(time(21, 15), time(22, 20)),
        ),
        awkward="You did know Emily, from work. There is no use pretending otherwise.",
        truth=("Walked the towpath alone. Nothing to do with Emily. The phone mast "
               "covers the whole hour they have to account for."),
    ),

    "canal_meeting": Brief(
        id="canal_meeting",
        tier=2,
        premise=("Thursday evening is yours to tell however you like - except for "
                 "twenty minutes of it, which you are going to have to cover."),
        denial=Concealment(
            DENIAL,
            "You met Emily at the Canal Street bridge at about 9:40. You argued, "
            "and you left her there alive.",
            window=(time(21, 30), time(22, 0)),
            location="bridge",
        ),
        substitution=Concealment(
            SUBSTITUTION,
            "Somewhere else you were for those twenty minutes, and someone who "
            "saw you there. Keep both the same every time you are asked.",
            window=(time(21, 30), time(22, 0)),
        ),
        awkward="She rang you twice that day. The calls are on record - denying them will not work.",
        truth=("Was there, argued about money she had lent them, left her alive. "
               "Innocent of her disappearance, concealing the meeting."),
    ),

    "false_alibi": Brief(
        id="false_alibi",
        tier=3,
        premise=("You have already told people you were at home all evening. You "
                 "are going to have to say it again, in detail, and make it hold."),
        denial=Concealment(
            DENIAL,
            "You were at a flat near the canal until late, with someone you will "
            "never name.",
            window=(time(21, 15), time(23, 59)),
            location="bridge",
        ),
        substitution=Concealment(
            SUBSTITUTION,
            "Your evening at home, invented in full - what you ate, what you "
            "watched, who you spoke to. Expect to be asked for it backwards.",
            window=(time(19, 0), time(23, 59)),
        ),
        awkward="Your phone was on you all night, and it was not at your flat.",
        truth=("Nothing to do with Emily - covering an affair. The false alibi has "
               "to span five hours, which is what makes it hard to hold."),
    ),
}


def deal(tier: Optional[int] = None, rng: Optional[random.Random] = None) -> Brief:
    """Deal a concealment pair for a new interview.

    Random by design: the learner should not know from the outset how much they
    are carrying, which is what makes the detectives' interest feel like
    something to answer rather than a foregone conclusion.
    """
    r = rng or random
    pool = [b for b in BRIEFS.values() if tier is None or b.tier == tier]
    if not pool:
        pool = list(BRIEFS.values())
    return r.choice(pool)


def get(brief_id: str) -> Optional[Brief]:
    """Look up a brief by id.

    Interviews started under the old dealt-account design reference briefs that
    no longer exist. They cannot be resumed as they were - the premise itself
    changed - so rather than 404 the briefing screen and strand the learner
    behind a dead button, an unknown id deals a pair deterministically. The
    interview continues under the current design.
    """
    brief = BRIEFS.get(brief_id)
    if brief is not None:
        return brief
    if not brief_id:
        return None
    return deal(rng=random.Random(brief_id))
