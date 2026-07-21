"""The learner's secret brief - the hidden hand they are dealt each session.

This is what gives the engine a ground truth. Without one, "contradiction" can
only ever mean the learner disagreeing with themselves, and no outcome could be
fair: nothing they said could be true or false, only consistent or not.

Two design constraints, both pedagogical rather than dramatic:

  * Facts are SHORT and few. The learner has to hold these while producing a
    second language under time pressure. A brief that is a memory test stops
    being a language test.
  * The brief stays visible during the interview. The difficulty should come
    from using the language, not from recalling the card.

Innocent briefs are not soft options: each carries a fact that is true but
looks bad, so the learner must volunteer something uncomfortable and survive it.
That is the honest-but-awkward pressure that makes an innocent run playable.
"""
import random
from dataclasses import dataclass, field
from datetime import time
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class BriefFact:
    id: str
    text: str                                       # short, plain, learner-facing
    window: Optional[Tuple[time, time]] = None
    location: Optional[str] = None


@dataclass(frozen=True)
class Brief:
    id: str
    tier: int                                       # 1 = gentlest
    concealing: bool
    premise: str                                    # one line of framing
    facts: List[BriefFact]
    # What the learner is trying not to say. None for an innocent brief.
    conceal: Optional[str] = None
    # Engine-only. Never shown to the learner; used to judge their account.
    truth: str = ""
    # True but awkward - the learner has to own this or look evasive.
    awkward: Optional[str] = None

    def committed_blocks(self) -> List[BriefFact]:
        return [f for f in self.facts if f.window is not None]


BRIEFS: Dict[str, Brief] = {

    "innocent_missed_calls": Brief(
        id="innocent_missed_calls",
        tier=1,
        concealing=False,
        premise="You did nothing wrong on Thursday. But you ignored Emily's calls, and that is going to look bad.",
        facts=[
            BriefFact("cafe", "You were at the Blue Door cafe until about 8pm.",
                      (time(17, 30), time(20, 0)), "cafe"),
            BriefFact("train", "You took the train home from Whitcomb Street.",
                      (time(20, 0), time(20, 45)), "station"),
            BriefFact("home", "You were home from about 8:45pm. Alone.",
                      (time(20, 45), time(23, 59)), "home"),
            BriefFact("knew", "You knew Emily from work. Not well."),
            BriefFact("calls", "Emily rang you twice. You ignored both calls."),
        ],
        awkward="You ignored her calls because you had argued about work. You are not proud of it.",
        truth="Innocent. Nowhere near the canal. The ignored calls are the only thing against them.",
    ),

    "innocent_wrong_place": Brief(
        id="innocent_wrong_place",
        tier=2,
        concealing=False,
        premise="You were near the canal that night, for a completely ordinary reason. Nobody can confirm it.",
        facts=[
            BriefFact("cafe", "You were at the Blue Door cafe until about 9pm.",
                      (time(18, 0), time(21, 0)), "cafe"),
            BriefFact("walk", "You walked home past the canal, arriving about 10:20pm.",
                      (time(21, 0), time(22, 20)), "bridge"),
            BriefFact("alone", "You were alone. Nobody saw you."),
            BriefFact("knew", "You knew Emily. You had lunch with her sometimes."),
            BriefFact("nosee", "You did not see Emily that night."),
        ],
        awkward="You really were on that towpath at the time she vanished. That is simply true.",
        truth="Innocent, but genuinely in the wrong place. Every piece of evidence fits them, and none of it means anything.",
    ),

    "concealing_argument": Brief(
        id="concealing_argument",
        tier=2,
        concealing=True,
        premise="You met Emily at the bridge and argued. She was alive when you left. You do not want to admit you were there.",
        facts=[
            BriefFact("met", "You met Emily at the Canal Street bridge at about 9:40pm.",
                      (time(21, 40), time(22, 0)), "bridge"),
            BriefFact("money", "You argued about money she had lent you."),
            BriefFact("left", "You left her there at about 10pm. She was fine."),
            BriefFact("walked", "You walked home. You got in about 10:20pm.",
                      (time(22, 0), time(22, 20)), "home"),
        ],
        conceal="That you were at the bridge at all, and that you met Emily.",
        truth="Was there. Argued about a debt. Left her alive. Innocent of her disappearance, guilty of hiding the meeting.",
    ),

    "concealing_alibi": Brief(
        id="concealing_alibi",
        tier=3,
        concealing=True,
        premise="You were somewhere you should not have been, with someone you must not name. Your alibi is a lie you have to hold.",
        facts=[
            BriefFact("claim", "Your story: you were home all evening from 7pm.",
                      (time(19, 0), time(23, 59)), "home"),
            BriefFact("really", "Really you were at a flat near the canal until midnight."),
            BriefFact("who", "You were with someone whose name you will not give."),
            BriefFact("nosee", "You did not see Emily. That part is true."),
        ],
        conceal="Where you actually were, and who you were with.",
        truth="Nothing to do with Emily. Covering an affair. The false alibi will collapse under the phone evidence.",
    ),
}


def deal(tier: Optional[int] = None, rng: Optional[random.Random] = None) -> Brief:
    """Deal a brief for a new interview.

    Random by design: the learner should not know from the outset whether they
    are innocent this time, which is what makes the detectives' suspicion feel
    like something to answer rather than a foregone conclusion.
    """
    r = rng or random
    pool = [b for b in BRIEFS.values() if tier is None or b.tier == tier]
    if not pool:
        pool = list(BRIEFS.values())
    return r.choice(pool)


def get(brief_id: str) -> Optional[Brief]:
    return BRIEFS.get(brief_id)
