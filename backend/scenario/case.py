"""The case file: what is true, what the police hold, and how they can say it.

Separated from the agents and the engine so the scenario can be swapped without
touching either. Everything the detectives could ever know lives here.

Evidence is structured rather than free text because Strategic Use of Evidence
needs three things the old flat list of strings could not provide: a strength
ranking, the three disclosure levels of the Evidence Framing Matrix, and a
machine-checkable statement of what each item contradicts. Without the last of
these the engine cannot tell that a learner has just walked into an item, which
is the entire point of SUE.
"""
from dataclasses import dataclass, field
from datetime import time
from typing import Dict, List, Optional, Tuple

# The accounted-for window. Everything outside it is out of scope.
WINDOW_START = time(17, 0)
WINDOW_END = time(23, 59)


@dataclass(frozen=True)
class Location:
    id: str
    name: str
    # Minutes on foot to other locations. Used by the Timeline Validator to spot
    # journeys that could not have happened in the time claimed.
    walk_minutes: Dict[str, int] = field(default_factory=dict)


LOCATIONS: Dict[str, Location] = {
    "cafe": Location("cafe", "the Blue Door cafe on Whitcomb Street",
                     {"bridge": 25, "home": 35, "station": 10}),
    "bridge": Location("bridge", "the Canal Street bridge",
                       {"cafe": 25, "home": 20, "station": 30}),
    "home": Location("home", "the subject's flat",
                     {"cafe": 35, "bridge": 20, "station": 40}),
    "station": Location("station", "Whitcomb Street station",
                        {"cafe": 10, "bridge": 30, "home": 40}),
}


@dataclass(frozen=True)
class Evidence:
    id: str
    # What the police actually hold. Never shown to the learner verbatim - it is
    # delivered through one of the framing levels below.
    fact: str
    strength: int                       # 1 weak, 2 moderate, 3 strong
    framing: Dict[str, str]             # vague | moderate | precise
    # If set, this item places the subject somewhere at a time. The engine uses
    # it to detect a clash with whatever the learner has committed to.
    window: Optional[Tuple[time, time]] = None
    location: Optional[str] = None
    # Only disclose once the learner has committed to an account. Disclosing
    # early would tell them what to avoid - the failure SUE exists to prevent.
    requires_commitment: bool = True
    about_subject: bool = True          # False = about Emily, not the learner


EVIDENCE: Dict[str, Evidence] = {
    "missing_report": Evidence(
        id="missing_report",
        fact="Emily Parker has been reported missing since Thursday evening.",
        strength=1,
        framing={
            "vague": "We're looking into the whereabouts of someone.",
            "moderate": "A woman has been reported missing since Thursday.",
            "precise": "Emily Parker has not been seen since Thursday evening.",
        },
        requires_commitment=False,
        about_subject=False,
    ),
    "emily_text": Evidence(
        id="emily_text",
        fact="Emily texted a friend at 8:15pm saying she was 'meeting someone to sort things out'.",
        strength=2,
        framing={
            "vague": "We know she had arranged to see somebody.",
            "moderate": "Emily told someone she was meeting a person that evening.",
            "precise": "At 8:15pm Emily texted a friend that she was 'meeting someone to sort things out'.",
        },
        window=(time(20, 15), time(20, 15)),
        requires_commitment=False,
        about_subject=False,
    ),
    "phone_ping": Evidence(
        id="phone_ping",
        fact="Emily's phone last connected at 9:47pm near the Canal Street bridge.",
        strength=2,
        framing={
            "vague": "We have a rough idea where she ended up.",
            "moderate": "Her phone was active near the canal that night.",
            "precise": "Emily's phone last connected at 9:47pm, by the Canal Street bridge.",
        },
        window=(time(21, 47), time(21, 47)),
        location="bridge",
        requires_commitment=False,
        about_subject=False,
    ),
    "phone_records": Evidence(
        id="phone_records",
        fact="Emily called the subject twice on Thursday: 4:12pm and 7:58pm.",
        strength=3,
        framing={
            "vague": "There's been contact between you and Emily we'd like to understand.",
            "moderate": "Your number appears in Emily's call records for that day.",
            "precise": "Emily rang you twice on Thursday. 4:12 in the afternoon, and 7:58 that evening.",
        },
        window=(time(19, 58), time(19, 58)),
    ),
    "witness_sighting": Evidence(
        id="witness_sighting",
        fact="A witness saw someone matching the subject's description near the canal at about 9:30pm.",
        strength=2,
        framing={
            "vague": "Someone was seen in the area that night.",
            "moderate": "A witness describes a man near the canal at around half nine.",
            "precise": "A witness puts someone matching your build on the towpath at about 9:30pm.",
        },
        window=(time(21, 30), time(21, 30)),
        location="bridge",
    ),
    "cell_tower": Evidence(
        id="cell_tower",
        fact="The subject's phone used a mast covering Canal Street between 9:15pm and 10:20pm.",
        strength=3,
        framing={
            "vague": "We have information about your movements that evening.",
            "moderate": "Your phone was not where you've suggested you were.",
            "precise": "Your phone used a mast covering Canal Street from 9:15 until 10:20 that night.",
        },
        window=(time(21, 15), time(22, 20)),
        location="bridge",
    ),
    "cctv_figure": Evidence(
        id="cctv_figure",
        fact="Shop CCTV shows a figure in a dark jacket walking toward the bridge at 9:38pm.",
        strength=2,
        framing={
            "vague": "There is camera footage from that area.",
            "moderate": "A camera picked someone up heading toward the bridge.",
            "precise": "At 9:38pm a shop camera filmed a man in a dark jacket walking toward the bridge.",
        },
        window=(time(21, 38), time(21, 38)),
        location="bridge",
    ),
    "colleague_dispute": Evidence(
        id="colleague_dispute",
        fact="A colleague says Emily had been in a dispute with someone she would not name.",
        strength=1,
        framing={
            "vague": "Emily had something on her mind recently.",
            "moderate": "We understand Emily had fallen out with somebody.",
            "precise": "A colleague tells us Emily was in a dispute. She wouldn't say who with.",
        },
    ),
    "bank_card": Evidence(
        id="bank_card",
        fact="Emily's bank card was used at a petrol station at 11:02pm, three miles toward the motorway.",
        strength=2,
        framing={
            "vague": "There was activity on her account later that night.",
            "moderate": "Her card was used after she was last seen.",
            "precise": "Emily's card was used at 11:02pm at a petrol station three miles out, toward the motorway.",
        },
        window=(time(23, 2), time(23, 2)),
        about_subject=False,
    ),
    "shoe_print": Evidence(
        id="shoe_print",
        fact="A partial shoe print was recovered from the towpath. Common trainer brand.",
        strength=1,
        framing={
            "vague": "Forensics have recovered material from the scene.",
            "moderate": "There's a footprint on the towpath we're working on.",
            "precise": "A partial print from the towpath. Common brand of trainer, so it proves little on its own.",
        },
        location="bridge",
    ),
}


# Ordered weakest to strongest. The Challenge phase works up this list rather
# than opening with the strongest item, so the learner commits before they know
# what is coming.
DISCLOSURE_ORDER: List[str] = [
    "missing_report", "colleague_dispute", "emily_text", "phone_ping",
    "shoe_print", "witness_sighting", "cctv_figure", "bank_card",
    "phone_records", "cell_tower",
]

# The topics an interviewer is expected to cover before Closure. The director
# uses these to know when a topic segment has ended - one of the five documented
# hand-off triggers between the two interviewers.
TOPICS: List[Dict[str, str]] = [
    {"id": "identity", "label": "identity and personal details"},
    {"id": "relationship", "label": "relationship to Emily Parker"},
    {"id": "timeline", "label": "movements between 5pm and midnight on Thursday"},
    {"id": "contact", "label": "contact with Emily that day"},
    {"id": "canal", "label": "presence near Canal Street"},
]


def evidence_for(claim_window: Tuple[time, time], location: Optional[str]) -> List[Evidence]:
    """Evidence that clashes with a claim of being at `location` during `window`.

    This is the mechanical half of Strategic Use of Evidence: the learner
    commits to being somewhere, and the engine can say which items that walks
    into, without anyone having written the confrontation by hand.
    """
    start, end = claim_window
    out = []
    for ev in EVIDENCE.values():
        if not ev.about_subject or ev.window is None or ev.location is None:
            continue
        if location is not None and ev.location == location:
            continue                        # consistent, not a clash
        ev_start, ev_end = ev.window
        if ev_start <= end and start <= ev_end:   # overlapping in time
            out.append(ev)
    return sorted(out, key=lambda e: e.strength)
