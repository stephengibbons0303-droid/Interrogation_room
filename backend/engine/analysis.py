"""Content analysis of a learner turn.

Follows the taxonomy's central finding: behavioural cues are worthless
(Bond & DePaulo 2006 - 54% accuracy across 24,483 judges), while verbal content
carries real signal, with total quantity of detail the single most diagnostic cue.

Two things this module must never do:

  * Penalise language quality. Errors, accent, hesitation and short-but-
    responsive answers are the learner practising. Pressure comes from the
    story and from deliberate evasion, never from how well they said it.
  * Treat hedging or self-correction as suspicious. CBCA counts spontaneous
    corrections, admissions of forgetting and doubts about one's own testimony
    as markers of *truthful* accounts. They score positively here.

No LLM and no I/O, so it is unit-testable. The one judgement that genuinely
needs a model - did this answer the question that was asked - is passed in.
"""
import re
from dataclasses import dataclass, field
from typing import List, Optional

# Sensory and perceptual detail: the Reality Monitoring signal for an
# experienced rather than imagined event.
_SENSORY = re.compile(
    r"\b(saw|heard|smell(?:ed|t)?|loud|quiet|cold|warm|hot|dark|bright|rain|"
    r"wet|noisy|music|voice|red|blue|green|black|white|yellow|smell|taste)\b", re.I)

# Spontaneous corrections - CBCA criterion, marker of genuine recall.
_CORRECTION = re.compile(
    r"\b(no wait|wait no|actually|sorry,? i mean|i mean|no,? it was|"
    r"or rather|let me think)\b", re.I)

# Admissions of uncertainty. Also a truthfulness marker, not a weakness.
_HEDGE = re.compile(
    r"\b(maybe|perhaps|i think|i guess|probably|about|around|roughly|"
    r"i'?m not sure|i can'?t remember|i don'?t remember|something like)\b", re.I)

_TIME_REF = re.compile(
    r"\b(\d{1,2}[:.]\d{2}|\d{1,2}\s?(?:am|pm)|o'?clock|midnight|noon|"
    r"morning|afternoon|evening|night|half past|quarter)\b", re.I)

_PLACE_REF = re.compile(
    r"\b(cafe|café|bridge|canal|home|flat|house|station|street|road|"
    r"shop|bar|pub|park|towpath)\b", re.I)

# The learner is struggling with the language, not dodging the question. These
# must never be read as evasion.
_STRUGGLE = re.compile(
    r"\b(sorry|pardon|what\?|again please|say again|repeat|i don'?t understand|"
    r"how do you say|what is the word|what'?s the word|i don'?t know how)\b", re.I)

# A deliberate, competent refusal to engage.
_REFUSAL = re.compile(
    r"\b(no comment|i'?m not answering|i won'?t answer|i don'?t have to|"
    r"am i under arrest|i want a lawyer|i want a solicitor|talk to my lawyer)\b", re.I)


@dataclass
class TurnAnalysis:
    words: int = 0
    sensory: int = 0
    corrections: int = 0
    hedges: int = 0
    time_refs: int = 0
    place_refs: int = 0

    responsive: bool = True
    struggling: bool = False
    refusal: bool = False

    @property
    def evasive(self) -> bool:
        """Deliberate dodging - the only thing here that may raise pressure.

        A refusal counts. Failing to address the question counts *only* when the
        learner is not visibly struggling: an L2 speaker who has lost the thread
        and one who is stonewalling look identical by length alone, and guessing
        wrong against a struggling learner is the failure mode that matters.
        """
        if self.refusal:
            return True
        return (not self.responsive) and (not self.struggling)

    @property
    def richness(self) -> float:
        """Detail score, 0..1 - feeds exculpation only, never pressure.

        Quantity of detail dominates because the research puts it first, with
        sensory and contextual grounding as secondary contributors.
        """
        volume = min(self.words / 45.0, 1.0)
        grounding = min((self.time_refs + self.place_refs) / 4.0, 1.0)
        texture = min((self.sensory + self.corrections) / 3.0, 1.0)
        return round(0.5 * volume + 0.3 * grounding + 0.2 * texture, 3)


def analyse(text: str, responsive: Optional[bool] = None) -> TurnAnalysis:
    """Score one learner turn.

    `responsive` comes from the model's read of whether the turn addressed the
    question asked; when it is unknown we assume it did, because the cost of
    wrongly calling a learner evasive is far higher than missing one dodge.
    """
    body = (text or "").strip()
    words = len(body.split())

    a = TurnAnalysis(
        words=words,
        sensory=len(_SENSORY.findall(body)),
        corrections=len(_CORRECTION.findall(body)),
        hedges=len(_HEDGE.findall(body)),
        time_refs=len(_TIME_REF.findall(body)),
        place_refs=len(_PLACE_REF.findall(body)),
        responsive=True if responsive is None else responsive,
        refusal=bool(_REFUSAL.search(body)),
    )

    # Struggling: an explicit appeal for help, or a very short turn that is
    # mostly hedging - someone reaching for words rather than withholding them.
    a.struggling = bool(_STRUGGLE.search(body)) or (words <= 4 and a.hedges > 0)
    return a
