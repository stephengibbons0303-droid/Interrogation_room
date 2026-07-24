"""LLM plumbing and the turn loop.

The engine (backend/engine/) decides what happens; this module asks the model to
say it well and to report back what the learner committed to. One structured
call per turn, so pacing does not regress.

Character material lives in prompts.py, techniques in engine/tactics.py. What
remains here is the bit that talks to Azure.
"""
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain_openai import (AzureChatOpenAI, AzureOpenAIEmbeddings, ChatOpenAI,
                              OpenAIEmbeddings)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.embeddings import Embeddings
from langchain_chroma import Chroma
from pydantic import BaseModel, Field

import prompts
from scenario import briefs as briefs_mod
from engine import director as dr
from engine.analysis import analyse
from engine.state import InterviewState, Stage
from engine.timeline import build as build_timeline

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


class LLMUnavailable(Exception):
    """A configured LLM failed or returned nothing usable this turn.

    Distinct from Mock Mode (no LLM configured at all, which is a legitimate
    local-dev state that returns a visible placeholder). This is a transient
    fault, so the endpoint turns it into a retryable 503 and persists nothing -
    rather than writing the "[MOCK MODE ...]" placeholder into the permanent
    transcript as though a detective had said it, and losing the learner's turn.
    """

# Anchored to this file's directory rather than the process working directory.
# "./chroma_db" meant the detectives' memory depended on where the server was
# launched from: start it one directory up and Chroma quietly builds a new,
# empty store, so every previous statement is forgotten with no error shown.
CHROMA_DIR = os.getenv("CHROMA_DIR") or str(BASE_DIR / "chroma_db")


class LocalEmbeddings(Embeddings):
    """LangChain adapter over the ONNX MiniLM model bundled with chromadb.

    Fallback for when there is no embedding deployment available - the Azure
    resource currently only has a chat deployment, and embeddings need their own.
    Runs locally on the already-installed onnxruntime: no key, no cost.
    """

    def __init__(self):
        from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2
        self._fn = ONNXMiniLM_L6_V2()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [[float(x) for x in vec] for vec in self._fn(list(texts))]

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


# ─────────────────────────────────────────────────────────────────────────────
# SHARED RESOURCES - built once per process, not per interview.
# ─────────────────────────────────────────────────────────────────────────────

_LLM = None
_VECTOR_STORE = None
_RESOURCES_READY = False


def _build_llm():
    """Azure OpenAI if configured, else OpenAI, else None (Mock Mode)."""
    if os.getenv("AZURE_OPENAI_API_KEY") and os.getenv("AZURE_OPENAI_ENDPOINT"):
        deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        print(f"LLM: Azure OpenAI, deployment '{deployment}'")
        return AzureChatOpenAI(
            azure_deployment=deployment,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"),
            temperature=0.75,
        )
    if os.getenv("OPENAI_API_KEY"):
        print("LLM: OpenAI gpt-4o")
        return ChatOpenAI(model="gpt-4o", temperature=0.75)
    return None


def _build_vector_store():
    """Semantic recall over prior statements. Complements the engine's structured
    claims rather than replacing them: this catches a rephrasing the extractor
    did not turn into a claim."""
    embeddings, tag = None, None
    azure_embed = os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT")
    if azure_embed and os.getenv("AZURE_OPENAI_API_KEY"):
        embeddings = AzureOpenAIEmbeddings(
            azure_deployment=azure_embed,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview"))
        tag = "azure"
    elif os.getenv("OPENAI_API_KEY"):
        embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        tag = "openai"
    else:
        try:
            embeddings, tag = LocalEmbeddings(), "local"
            print("Embeddings: local ONNX MiniLM (no embedding deployment found)")
        except Exception as e:
            print(f"WARNING: local embeddings unavailable ({e})")
            return None
    try:
        # Namespaced per backend: Chroma fixes a collection's dimensionality at
        # creation and these models disagree (384 vs 1536).
        return Chroma(collection_name=f"interrogation_memory_{tag}",
                      embedding_function=embeddings, persist_directory=CHROMA_DIR)
    except Exception as e:
        print(f"WARNING: vector store init failed ({e})")
        return None


def init_resources() -> None:
    global _LLM, _VECTOR_STORE, _RESOURCES_READY
    if _RESOURCES_READY:
        return
    _RESOURCES_READY = True
    _LLM = _build_llm()
    if _LLM is None:
        print("WARNING: No LLM configured. Falling back to Mock Mode.")
        return
    _VECTOR_STORE = _build_vector_store()
    if _VECTOR_STORE is None:
        print("WARNING: No embeddings configured - semantic recall is OFF.")


# ─────────────────────────────────────────────────────────────────────────────
# STRUCTURED OUTPUT - the detectives' line AND what the learner committed to,
# in one call. Two calls would double the wait before the learner hears anything.
# ─────────────────────────────────────────────────────────────────────────────

class ClaimOut(BaseModel):
    text: str = Field(description="the claim in the subject's own words, condensed")
    start_min: Optional[int] = Field(None, description="start, minutes past midnight; 9:30pm = 1290")
    end_min: Optional[int] = Field(None, description="end, minutes past midnight")
    location: Optional[str] = Field(None, description="one of: cafe, bridge, home, station, or null")
    place: Optional[str] = Field(
        None, description=("where they said they were, in their own words - 'the Indian "
                           "restaurant', 'the Pig and Whistle', 'work'. Give this for EVERY "
                           "claim that names a place, including ones that are not in the "
                           "location list. Use the same wording each time for the same place."))
    activity: Optional[str] = None
    people: List[str] = Field(default_factory=list)
    episodic: bool = Field(
        True,
        description=("true when this is specific to THAT night - pinned to a clock "
                     "time or a one-off event ('a text came in about quarter past "
                     "eight', 'the episode finished and it said 10:20'). false when "
                     "it describes what they USUALLY or ALWAYS do ('I put my keys on "
                     "the table', 'I take my shoes off at the door'). Habitual "
                     "description is welcome and worth having - it simply cannot be "
                     "checked against anything, so mark it honestly."))


class UtteranceOut(BaseModel):
    speaker: str = Field(description="Reynolds or Chen")
    text: str = Field(description="spoken words only - no stage directions, no asterisks")
    addressed_to: str = Field("learner", description="learner, or partner for an aside")


class TurnOut(BaseModel):
    utterances: List[UtteranceOut]
    tactic_used: str = Field(description="the id of the tactic you chose")
    emotion: Optional[str] = Field(None, description="one word for the delivery")
    responsive: bool = Field(True, description="did the subject's last message address the question asked")
    subject_name: Optional[str] = Field(
        None,
        description=("the subject's own name, ONLY if they have clearly given it as their "
                     "name. Null otherwise. Never a greeting, courtesy or acknowledgement "
                     "such as 'thank you', 'yes', 'I understand' or 'sorry'."))
    topic: Optional[str] = Field(
        None, description=("a short, STABLE label for the stretch of the interview this "
                           "turn is about - 'the cafe', 'the walk home', 'Emily'. Reuse "
                           "the same label while you stay on the same ground."))
    topic_complete: bool = Field(
        False, description=("true when you are DONE with the current topic and moving on - "
                            "you have what you need from it and the next question will open "
                            "a different thread. This is what lets the interview register a "
                            "topic as covered, so set it whenever you change subject."))
    chen_vouched_claim: bool = Field(
        False, description="true if Chen pushed them to commit to a specific detail this turn")
    premise_corrected: Optional[bool] = Field(
        None, description=("ONLY when told a false detail was asserted last turn: true if "
                           "the subject's reply pushed back on or corrected it, false if "
                           "they let it stand. Null otherwise."))
    claims: List[ClaimOut] = Field(default_factory=list)


# A leading "[Reynolds]: " / "[Chen]: " label the model sometimes copies from its
# own history. Turns are fed back as "[<agent>]: <text>" (see _context_messages),
# and the model occasionally mimics that framing in the reply itself. Left in, the
# label renders in the speech bubble AND is read aloud by TTS, then compounds when
# the labelled line is fed back the next turn. RULES already forbids it; this is
# the backstop for when the model does it anyway. Brackets are banned in a reply
# outright (RULES rule 8), so any leading "[...]:" is a self-label artifact.
_SELF_LABEL_RX = re.compile(r"^\s*\[[^\]\n]{1,40}\]:\s*")


def _strip_self_label(text: str) -> str:
    out, prev = (text or ""), None
    while out != prev:                     # peel a stacked "[Reynolds]: [Reynolds]:" too
        prev = out
        out = _SELF_LABEL_RX.sub("", out, count=1)
    return out.strip()


def _validated_tactic(reported: Optional[str], options) -> str:
    """The tactic the model claims it used, constrained to one it was offered.

    The shortlist is presented as "[tactic_id] instruction" and the model
    sometimes echoes the brackets, so those are stripped first. But the deeper
    problem is a model that reports a tactic it was never offered - a stale id
    lingering in the chat history, or a plain hallucination. Every gate in
    _apply keys off this string (cooldowns, evidence and challenge raised-marking,
    retelling arming), so an unoffered id bypasses the shortlist's stage,
    precondition and cooldown checks entirely: a phantom "challenge_contradiction"
    reported in Probe marks evidence raised and can flip the verdict to DETAINED;
    a phantom "reverse_chronology" re-arms the retelling window past its cap.

    Anything not on the shortlist we actually presented collapses to the top
    offer, which is a legal move for this stage and state by construction. With
    no shortlist (an empty fallback turn) the cleaned value passes through.
    """
    cleaned = (reported or "").strip().strip("[]").strip()
    offered = [t.id for t in (options or [])]
    if offered and cleaned not in offered:
        return offered[0]
    return cleaned


class InterrogationAgent:
    """One live interrogation, driven by the engine."""

    def __init__(self, interview_id: str = None, history: List[Dict[str, Any]] = None,
                 state: Optional[InterviewState] = None, player_name: str = None):
        init_resources()
        self.interview_id = interview_id
        self.llm = _LLM
        self.vector_store = _VECTOR_STORE
        self.history: List[Dict[str, Any]] = history if history is not None else []
        self.state = state or InterviewState()
        self.player_name = player_name
        self.brief = briefs_mod.get(self.state.brief_id) if self.state.brief_id else None

    # ── helpers ─────────────────────────────────────────────────────────────

    def _recall(self, message: str) -> str:
        if not (self.vector_store and self.state.turn > 3):
            return ""
        try:
            hits = self.vector_store.similarity_search(
                message, k=3, filter={"interview_id": self.interview_id})
            return "\n".join(f'  - "{h.page_content}"' for h in hits)
        except Exception as e:
            print(f"WARNING: memory recall failed, continuing without it ({e})")
            return ""

    def _remember(self, message: str) -> None:
        if not self.vector_store:
            return
        try:
            self.vector_store.add_texts(
                texts=[message],
                metadatas=[{"interview_id": self.interview_id or "unknown"}])
        except Exception as e:
            print(f"WARNING: memory write failed ({e})")

    # The name now comes from the model's structured extraction, not a heuristic.
    # The old rule - "a short message with no question words is probably a name" -
    # took "Yes, thank you." as the subject's name, because the stop-word check
    # compared "yes," with its comma and never matched. The detectives then spent
    # the rest of the interview addressing them as Mr Thank You.

    # ── the turn ────────────────────────────────────────────────────────────

    def process_message(self, user_message: str) -> Dict[str, Any]:
        if not self.llm:
            return self._mock(user_message)

        is_silence = user_message.strip() == "[SILENCE]"
        # A [SILENCE] is not persisted as a user turn (sessions._persist_turn skips
        # it), so it must not enter the live history either - otherwise a cached
        # agent carries [SILENCE] rows the rehydrated one won't, and the two LLM
        # contexts diverge the moment the agent is evicted and rebuilt from the DB.
        # The model still learns of the silence: the system prompt says so
        # explicitly below, and the detective's reaction persists as an agent turn.
        if not is_silence:
            self.history.append({"role": "user", "content": user_message})

        if not is_silence:
            self.state.turn += 1

        # Preliminary read. Struggle and refusal are detectable without the model;
        # only "did it answer the question" needs one, and that arrives below.
        prelim = analyse("" if is_silence else user_message)

        # Cooldowns tick per TURN, not per event. A silence is not a turn - the
        # learner said nothing - so ticking here let an unattended mic (which
        # re-sends [SILENCE] every 4-8s) erode every cooldown by wall-clock.
        if not is_silence:
            self.state.tick_cooldowns()

        # Advance the stage BEFORE choosing what to say. Advancing afterwards
        # meant the turn that ended the interview was still generated as a
        # challenge question, and then it simply stopped - no closing exchange,
        # no sign-off, just an outcome screen. Deciding the stage first means a
        # closing turn is written as one.
        # Build the timeline once and share it: advance_stage and build_context
        # both need it, over the same claims (ingest does not run until _apply).
        report = build_timeline(self.state.claims)
        dr.advance_stage(self.state, report)

        ctx = dr.build_context(self.state, self.brief, prelim, report=report)
        closing = Stage(self.state.stage) is Stage.CLOSURE
        speaker, reason = dr.select_speaker(ctx)
        options = dr.shortlist(ctx, speaker)
        # An aside is a two-voice beat with a three-utterance contract (two
        # detectives confer, then one turns back to the subject). Run one ONLY
        # when the aside tactic is the strongest available play - and when it is
        # not, drop it from the shortlist entirely. Offering it at position 2-3
        # without imposing the contract let the model half-produce one: two
        # partners conferring and no line back to the subject, leaving the learner
        # with nothing to answer. Keyed to options[0] so the format we impose and
        # the tactics we offer can never disagree.
        aside = bool(options) and options[0].two_voices
        if not aside:
            options = [t for t in options if not t.two_voices] or options
        disclosure = dr.next_disclosure(self.state) if Stage(
            self.state.stage) is Stage.CHALLENGE else None

        # The misquote only enters the prompt when the tactic is actually on
        # offer - otherwise the model reads bait it is not allowed to use.
        offered_premise = ctx.false_premise if any(
            t.id == "false_premise" for t in options) else None

        system = prompts.build_system_prompt(
            speaker, self.state, ctx.timeline, options,
            disclosure=disclosure, aside=aside, closing=closing,
            player_name=self.player_name, thin=ctx.thin,
            false_premise=offered_premise)

        recall = self._recall(user_message)
        if recall:
            system += (f"\n\nEARLIER STATEMENTS THAT RESEMBLE THIS ONE:\n{recall}\n"
                       "If one conflicts with what they just said, work it in naturally.")
        if is_silence:
            system += ("\n\nTHE SUBJECT HAS SAID NOTHING for a long moment. React to the "
                       "silence itself. Do not ask several questions.")

        # Timed because "it felt slow on turn 2" is not something anyone can act
        # on. Turn 1 never reaches here - the opening line is hard-coded - so
        # turn 2 is the first call this process makes and pays whatever cold
        # start there is. Logging it says whether that is the whole story.
        started = time.perf_counter()
        try:
            result: TurnOut = self.llm.with_structured_output(TurnOut).invoke(
                [SystemMessage(content=system), *self._context_messages()])
        except Exception as e:
            # A configured model that errors is a transient fault, not Mock Mode.
            # Raise so the endpoint returns a retryable 503 and persists nothing;
            # the caller drops the (already-advanced) cached agent so a retry
            # starts clean rather than double-counting this turn.
            print(f"Error invoking LLM: {e}")
            raise LLMUnavailable(str(e))
        print(f"[turn {self.state.turn}] LLM {time.perf_counter() - started:.2f}s "
              f"({len(system)} chars of system prompt, "
              f"{len(self.history[-14:])} messages of history)")

        return self._apply(result, user_message, is_silence, prelim, ctx,
                           speaker, reason, disclosure, offered_premise, options)

    def _context_messages(self):
        out = []
        for msg in self.history[-14:]:
            if msg["role"] == "user":
                out.append(HumanMessage(content=msg["content"]))
            else:
                out.append(AIMessage(content=f"[{msg.get('agent', 'Agent')}]: {msg['content']}"))
        return out

    def _apply(self, result: TurnOut, user_message: str, is_silence: bool,
               prelim, ctx, speaker: str, reason: str, disclosure,
               offered_premise=None, options=None) -> Dict[str, Any]:
        """Fold the model's reply back into engine state."""
        # Strip any "[Name]:" label the model copied from its own fed-back history
        # before anything downstream reads the text (bubble, TTS, re-feed).
        for u in result.utterances:
            u.text = _strip_self_label(u.text)
        # Up to three: an aside is two detectives conferring plus the one who
        # then turns back to the subject.
        utterances = [u for u in result.utterances if u.text.strip()][:3]
        if not utterances:
            # A configured model returned no usable line. Same as a call failure:
            # do not persist a placeholder as a detective's turn.
            raise LLMUnavailable("model returned no utterances")

        for u in utterances:
            if u.speaker not in ("Reynolds", "Chen"):
                u.speaker = speaker
            self.history.append({"role": "assistant", "content": u.text,
                                 "agent": u.speaker})
            dr.note_speaker(self.state, u.speaker)

        is_aside = any(u.addressed_to == "partner" for u in utterances)
        if is_aside:
            self.state.asides_this_stage += 1

        # Constrain the reported tactic to one we actually offered (see
        # _validated_tactic). Everything below keys off this string, so an
        # unoffered id would bypass every shortlist gate.
        cleaned = _validated_tactic(result.tactic_used, options)
        if cleaned != (result.tactic_used or "").strip().strip("[]").strip() and options:
            print(f"WARNING: model reported unoffered tactic "
                  f"{result.tactic_used!r}; using {cleaned!r}")
        result.tactic_used = cleaned

        # First clear statement of their name wins; later turns cannot rewrite it.
        if not self.player_name and result.subject_name:
            candidate = result.subject_name.strip().strip('.').strip()
            if candidate and len(candidate.split()) <= 5:
                self.player_name = candidate

        self.state.cooldowns.update(self._cooldown_for(result.tactic_used))

        # Evidence the model was told to put this turn is now on the record, at
        # the level it was framed. Done before ingest so the same item is not
        # immediately re-raised as a fresh clash.
        if result.tactic_used == "sue_disclose" and disclosure:
            ev_id, level = disclosure
            self.state.disclosed[ev_id] = level
            for c in self.state.contradictions:
                if c.evidence_id == ev_id:
                    c.raised = True
        elif result.tactic_used == "challenge_contradiction":
            for c in self.state.open_contradictions[:1]:
                c.raised = True

        # Extraction -> claims, contradictions, pressure, Chen, stage, outcome.
        final = analyse("" if is_silence else user_message,
                        responsive=True if is_silence else result.responsive)
        extraction = dr.Extraction(
            claims=[c.model_dump() for c in result.claims] if not is_silence else [],
            responsive=True if is_silence else result.responsive,
            topic=result.topic, topic_complete=result.topic_complete,
            chen_vouched_claim=result.chen_vouched_claim,
        )
        claims_before = len(self.state.claims)
        new_contradictions = dr.ingest(self.state, extraction,
                                       self.brief, self.state.turn)

        # Settle last turn's misquote against this reply - BEFORE arming a new
        # one, or a probe posed this turn would be scored against the answer to
        # the previous question.
        dr.resolve_premise(self.state, result.premise_corrected,
                           self.state.claims[claims_before:])
        if result.tactic_used == "false_premise" and offered_premise:
            self.state.premise_open = dict(offered_premise,
                                           posed_turn=self.state.turn)
            self.state.premises_posed += 1

        # Armed AFTER ingest on purpose. The claims folded in above came from
        # their answer to the previous question; the second telling does not
        # begin until they respond to the request being made this turn.
        dr.arm_retelling(self.state, result.tactic_used)
        # Pressure moves on what the learner did; on silence they did nothing, so
        # it must not move at all - otherwise an idling mic drains pressure to 0
        # on a clean account, or ratchets it to the 0.9 closure trigger on a dirty
        # one, ending the interview with nobody in the room.
        stung = False
        if not is_silence:
            dr.update_pressure(self.state, new_contradictions, final, ctx.timeline)
            stung = dr.update_chen(self.state, new_contradictions, prelim.struggling)

        # The stage was settled at the top of the turn, so the outcome now
        # follows a line that was actually written as a closing one.
        self.state.outcome = dr.decide_outcome(self.state)

        if not is_silence:
            self._remember(user_message)

        return {
            "utterances": [{"speaker": u.speaker, "text": u.text.strip(),
                            "addressed_to": u.addressed_to,
                            "emotion": result.emotion} for u in utterances],
            "tactic": result.tactic_used,
            "handoff_reason": reason,
            "stage": self.state.stage,
            "pressure": round(self.state.pressure, 3),
            "chen_stance": self.state.chen_stance,
            "sting": stung,
            "outcome": self.state.outcome,
            "turn": self.state.turn,
        }

    @staticmethod
    def _cooldown_for(tactic_id: str) -> Dict[str, int]:
        from engine.tactics import get as get_tactic
        t = get_tactic(tactic_id)
        return {tactic_id: t.cooldown} if t and t.cooldown else {}

    def _mock(self, user_message: str) -> Dict[str, Any]:
        return {
            "utterances": [{
                "speaker": "System",
                "text": "[MOCK MODE - no LLM configured] The detectives study you in silence.",
                "addressed_to": "learner", "emotion": "neutral"}],
            "tactic": "none",
            "handoff_reason": "mock",
            "stage": self.state.stage,
            "pressure": round(self.state.pressure, 3),
            "chen_stance": self.state.chen_stance,
            "sting": False,
            "outcome": None,
            "turn": self.state.turn,
        }
