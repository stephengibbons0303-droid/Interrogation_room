"""LLM plumbing and the turn loop.

The engine (backend/engine/) decides what happens; this module asks the model to
say it well and to report back what the learner committed to. One structured
call per turn, so pacing does not regress.

Character material lives in prompts.py, techniques in engine/tactics.py. What
remains here is the bit that talks to Azure.
"""
import os
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
    activity: Optional[str] = None
    people: List[str] = Field(default_factory=list)


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
    topic: Optional[str] = None
    topic_complete: bool = False
    chen_vouched_claim: bool = Field(
        False, description="true if Chen pushed them to commit to a specific detail this turn")
    claims: List[ClaimOut] = Field(default_factory=list)


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
        self.history.append({"role": "user", "content": user_message})

        if not is_silence:
            self.state.turn += 1

        # Preliminary read. Struggle and refusal are detectable without the model;
        # only "did it answer the question" needs one, and that arrives below.
        prelim = analyse("" if is_silence else user_message)

        self.state.tick_cooldowns()

        # Advance the stage BEFORE choosing what to say. Advancing afterwards
        # meant the turn that ended the interview was still generated as a
        # challenge question, and then it simply stopped - no closing exchange,
        # no sign-off, just an outcome screen. Deciding the stage first means a
        # closing turn is written as one.
        dr.advance_stage(self.state, build_timeline(self.state.claims))

        ctx = dr.build_context(self.state, self.brief, prelim)
        closing = Stage(self.state.stage) is Stage.CLOSURE
        speaker, reason = dr.select_speaker(ctx)
        options = dr.shortlist(ctx, speaker)
        aside = any(t.two_voices for t in options[:1])
        disclosure = dr.next_disclosure(self.state) if Stage(
            self.state.stage) is Stage.CHALLENGE else None

        system = prompts.build_system_prompt(
            speaker, self.state, ctx.timeline, options,
            disclosure=disclosure, aside=aside, closing=closing,
            player_name=self.player_name, thin=ctx.thin)

        recall = self._recall(user_message)
        if recall:
            system += (f"\n\nEARLIER STATEMENTS THAT RESEMBLE THIS ONE:\n{recall}\n"
                       "If one conflicts with what they just said, work it in naturally.")
        if is_silence:
            system += ("\n\nTHE SUBJECT HAS SAID NOTHING for a long moment. React to the "
                       "silence itself. Do not ask several questions.")

        try:
            result: TurnOut = self.llm.with_structured_output(TurnOut).invoke(
                [SystemMessage(content=system), *self._context_messages()])
        except Exception as e:
            print(f"Error invoking LLM: {e}")
            return self._mock(user_message)

        return self._apply(result, user_message, is_silence, prelim, ctx,
                           speaker, reason, disclosure)

    def _context_messages(self):
        out = []
        for msg in self.history[-14:]:
            if msg["role"] == "user":
                out.append(HumanMessage(content=msg["content"]))
            else:
                out.append(AIMessage(content=f"[{msg.get('agent', 'Agent')}]: {msg['content']}"))
        return out

    def _apply(self, result: TurnOut, user_message: str, is_silence: bool,
               prelim, ctx, speaker: str, reason: str, disclosure) -> Dict[str, Any]:
        """Fold the model's reply back into engine state."""
        # Up to three: an aside is two detectives conferring plus the one who
        # then turns back to the subject.
        utterances = [u for u in result.utterances if (u.text or "").strip()][:3]
        if not utterances:
            return self._mock(user_message)

        for u in utterances:
            if u.speaker not in ("Reynolds", "Chen"):
                u.speaker = speaker
            self.history.append({"role": "assistant", "content": u.text,
                                 "agent": u.speaker})
            dr.note_speaker(self.state, u.speaker)

        is_aside = any(u.addressed_to == "partner" for u in utterances)
        if is_aside:
            self.state.asides_this_stage += 1

        # The shortlist is presented as "[tactic_id] instruction", and the model
        # sometimes echoes the brackets back. Left unstripped, the cooldown is
        # keyed on "[minimisation]" and never matches "minimisation", so the
        # tactic could repeat every turn.
        result.tactic_used = (result.tactic_used or "").strip().strip("[]").strip()

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
        new_contradictions = dr.ingest(self.state, extraction, final,
                                       self.brief, self.state.turn)

        # Armed AFTER ingest on purpose. The claims folded in above came from
        # their answer to the previous question; the second telling does not
        # begin until they respond to the request being made this turn.
        dr.arm_retelling(self.state, result.tactic_used)
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
