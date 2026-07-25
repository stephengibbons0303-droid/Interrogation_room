"""Interview session management.

Each interview gets its own agent, keyed by interview id and rehydrated from the
database, so learners can dip out and resume and nothing is lost on restart.

Agents are cached in memory purely as an optimisation - the database is the
source of truth, so evicting a cached agent is always safe.
"""
import threading
from collections import OrderedDict
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

import uuid

from agent import InterrogationAgent, LLMUnavailable
from auth import get_current_user
from db import Claim as ClaimRow, Interview, Turn, User, get_db
from engine.state import InterviewState
from prompts import OPENING_LINE
from scenario import briefs as briefs_mod

router = APIRouter(prefix="/interviews", tags=["interviews"])

# Cap the cache so a long-running server with many learners cannot grow without
# bound. Evicted agents are rebuilt from the database on next use.
_MAX_CACHED_AGENTS = 64
_agents: "OrderedDict[str, InterrogationAgent]" = OrderedDict()
_lock = threading.Lock()

# One lock per interview, so two concurrent chats for the SAME interview (two
# tabs, or a silence trigger racing a typed send) run one after the other rather
# than interleaving mutations of a shared agent - or each hydrating its own and
# clobbering the other's engine_state on commit. `chat` is a sync endpoint, so
# FastAPI runs it in a threadpool and this really can happen. Bounded in lockstep
# with the agent cache; a lock evicted while still held simply finishes on its
# holder's reference, and the unique (interview_id, seq) index is the backstop.
_interview_locks: "OrderedDict[str, threading.Lock]" = OrderedDict()


def _interview_lock(interview_id: str) -> threading.Lock:
    with _lock:
        lk = _interview_locks.get(interview_id)
        if lk is None:
            lk = threading.Lock()
            _interview_locks[interview_id] = lk
            while len(_interview_locks) > _MAX_CACHED_AGENTS * 2:
                _interview_locks.popitem(last=False)
        else:
            _interview_locks.move_to_end(interview_id)
        return lk


def _hydrate(interview: Interview) -> InterrogationAgent:
    """Rebuild an agent from persisted rows, engine state included.

    The database is the source of truth: pressure, the half-built timeline,
    contradictions and Chen's stance all come back exactly as they were left.
    """
    history = []
    for t in interview.turns:
        if t.role == "user":
            history.append({"role": "user", "content": t.text})
        else:
            history.append({"role": "assistant", "content": t.text,
                            "agent": t.agent_name or "Reynolds"})

    state = InterviewState.from_dict(interview.engine_state)
    if not state.brief_id and interview.brief_id:
        state.brief_id = interview.brief_id

    return InterrogationAgent(
        interview_id=interview.id,
        history=history,
        state=state,
        player_name=interview.player_name,
    )


def get_agent(interview: Interview) -> InterrogationAgent:
    with _lock:
        agent = _agents.get(interview.id)
        if agent is not None:
            _agents.move_to_end(interview.id)
            return agent
    # Build outside the lock - hydration can be slow and must not block others.
    agent = _hydrate(interview)
    with _lock:
        _agents[interview.id] = agent
        _agents.move_to_end(interview.id)
        while len(_agents) > _MAX_CACHED_AGENTS:
            _agents.popitem(last=False)
    return agent


def drop_agent(interview_id: str) -> None:
    with _lock:
        _agents.pop(interview_id, None)


# ── schemas ──────────────────────────────────────────────────────────────────

class InterviewSummary(BaseModel):
    id: str
    status: str
    phase: str
    turn_count: int
    player_name: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    preview: Optional[str] = None
    outcome: Optional[str] = None


class ConcealmentOut(BaseModel):
    kind: str                              # denial | substitution
    text: str


class BriefOut(BaseModel):
    """The learner's own brief. Deliberately shown to them - holding it in a
    second language under pressure is the game; memorising it is not.

    No longer an account to recite. The evening is theirs to invent; what is
    dealt is the pair they have to work around."""
    id: str
    premise: str
    concealments: List[ConcealmentOut]
    awkward: Optional[str] = None


class TurnOut(BaseModel):
    seq: int
    role: str
    agent_name: Optional[str] = None
    text: str
    modality: Optional[str] = None
    addressed_to: Optional[str] = "learner"
    exchange_id: Optional[str] = None
    phase: Optional[str] = None
    emotion: Optional[str] = None


class InterviewDetail(InterviewSummary):
    turns: List[TurnOut] = []


class ChatRequest(BaseModel):
    message: str
    # How the learner produced this turn. Recorded per turn because it cannot be
    # reconstructed afterwards, and the post-session assessment credits speaking
    # and listening separately - a typed answer is not evidence of speaking.
    modality: str = "typed"          # typed | spoken | silence


class UtteranceOut(BaseModel):
    speaker: str
    text: str
    # "learner" or "partner". An aside is the detectives conferring in front of
    # them - overheard rather than addressed, and a harder listening task.
    addressed_to: str = "learner"
    emotion: Optional[str] = None


class ChatResponse(BaseModel):
    # A turn is usually one utterance; an aside is two.
    utterances: List[UtteranceOut]
    phase: str
    turn: int
    interview_id: str
    outcome: Optional[str] = None
    tactic: Optional[str] = None
    # The engine's decision trace for this turn - what it decided and why. For the
    # admin engine-trace view; ordinary clients ignore it.
    trace: Optional[dict] = None


def _summary(iv: Interview) -> InterviewSummary:
    first_user = next((t.text for t in iv.turns if t.role == "user"), None)
    return InterviewSummary(
        id=iv.id, status=iv.status, phase=iv.phase, turn_count=iv.turn_count,
        player_name=iv.player_name,
        created_at=iv.created_at.isoformat() if iv.created_at else None,
        updated_at=iv.updated_at.isoformat() if iv.updated_at else None,
        preview=(first_user[:80] if first_user else None),
        outcome=iv.outcome,
    )


def _owned(interview_id: str, user: User, db: Session) -> Interview:
    iv = db.query(Interview).filter(Interview.id == interview_id).first()
    # 404 rather than 403 for someone else's interview - do not confirm it exists.
    if iv is None or iv.user_id != user.id:
        raise HTTPException(status_code=404, detail="Interview not found")
    return iv


# ── routes ───────────────────────────────────────────────────────────────────

@router.get("", response_model=List[InterviewSummary])
def list_interviews(user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Resumable interviews for the signed-in learner, newest first."""
    # _summary reads each interview's turns for its preview, so eager-load them in
    # one batched query rather than letting the per-row access fire N lazy loads.
    rows = (db.query(Interview)
              .filter(Interview.user_id == user.id)
              .options(selectinload(Interview.turns))
              .order_by(Interview.updated_at.desc())
              .all())
    return [_summary(iv) for iv in rows]


@router.post("", response_model=InterviewSummary, status_code=201)
def create_interview(user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    """Start fresh. Existing interviews are left intact, not overwritten."""
    # Deal the hidden brief now, so the ground truth exists before the first
    # word is spoken. The learner sees their own; the detectives never do.
    brief = briefs_mod.deal()
    state = InterviewState(brief_id=brief.id)

    iv = Interview(user_id=user.id, brief_id=brief.id,
                   phase=state.stage, engine_state=state.to_dict())
    db.add(iv)
    db.flush()                              # assign iv.id before the opening Turn

    # The opening line is Turn 0. Persisting it here means a resumed transcript
    # starts with the question the learner answers, not with an answer to an
    # absent question - and it does not disturb seq numbering, which counts turns.
    db.add(Turn(interview_id=iv.id, seq=0, role="agent", agent_name="Reynolds",
                text=OPENING_LINE, modality="synthesised", addressed_to="learner",
                phase=state.stage, turn_number=0, emotion="measured"))
    db.commit()
    db.refresh(iv)
    return _summary(iv)


@router.get("/{interview_id}/brief", response_model=BriefOut)
def get_brief(interview_id: str, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """The learner's own brief, for the panel they keep open during the interview."""
    iv = _owned(interview_id, user, db)
    brief = briefs_mod.get(iv.brief_id or "")
    if brief is None:
        raise HTTPException(status_code=404, detail="No brief for this interview")
    return BriefOut(
        id=brief.id, premise=brief.premise,
        concealments=[ConcealmentOut(kind=c.kind, text=c.text)
                      for c in brief.concealments],
        awkward=brief.awkward,
    )


@router.get("/{interview_id}", response_model=InterviewDetail)
def get_interview(interview_id: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    iv = _owned(interview_id, user, db)
    detail = InterviewDetail(**_summary(iv).model_dump())
    detail.turns = [
        TurnOut(seq=t.seq, role=t.role, agent_name=t.agent_name, text=t.text,
                modality=t.modality, addressed_to=t.addressed_to or "learner",
                exchange_id=t.exchange_id, phase=t.phase, emotion=t.emotion)
        for t in iv.turns
    ]
    return detail


@router.get("/{interview_id}/trace", response_model=List[dict])
def get_trace(interview_id: str, user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """The engine's per-turn decision traces for one interview, in order.

    Dev/admin observability: what the engine decided each turn and why. Owner-
    scoped for now; role-gate it before exposing engine internals in a real
    deployment. One trace per exchange - silence and user rows carry none.
    """
    _owned(interview_id, user, db)                 # ownership check / 404 only
    rows = (db.query(Turn.decision_trace)
              .filter(Turn.interview_id == interview_id,
                      Turn.decision_trace.isnot(None))
              .order_by(Turn.seq)
              .all())
    return [r[0] for r in rows]


@router.delete("/{interview_id}", status_code=204)
def delete_interview(interview_id: str, user: User = Depends(get_current_user),
                     db: Session = Depends(get_db)):
    iv = _owned(interview_id, user, db)
    db.delete(iv)
    db.commit()
    drop_agent(interview_id)


@router.post("/{interview_id}/chat", response_model=ChatResponse)
def chat(interview_id: str, body: ChatRequest,
         user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Serialise the whole turn per interview: read, run the agent, and commit all
    # happen with no other chat for this interview interleaving. Held across
    # get_agent too, so the cache-miss case cannot hydrate two divergent agents.
    with _interview_lock(interview_id):
        iv = _owned(interview_id, user, db)
        if iv.outcome:
            raise HTTPException(status_code=409, detail="This interview has concluded")

        agent = get_agent(iv)
        is_silence = body.message.strip() == "[SILENCE]"
        try:
            result = agent.process_message(body.message)
            _persist_turn(db, iv, agent, result, body, is_silence)
            db.commit()
        except HTTPException:
            raise
        except LLMUnavailable:
            # Transient model fault. Nothing was committed; drop the cached agent
            # so the retry starts from the DB rather than double-counting, and
            # tell the client to try again instead of writing a fake turn.
            drop_agent(interview_id)
            raise HTTPException(
                status_code=503,
                detail="The interviewers are unavailable for a moment. Please try again.")
        except Exception:
            # process_message already advanced the cached agent's turn, history
            # and claims; the commit that would have recorded them just failed and
            # rolled back. The cached agent is now ahead of the database, so a
            # retry would double-count. Drop it: the next request rehydrates from
            # the DB, the true source of truth, and the failed turn is as if it
            # never happened.
            drop_agent(interview_id)
            raise

    utterances = result.get("utterances", [])
    return ChatResponse(
        utterances=[UtteranceOut(**u) for u in utterances],
        phase=result.get("stage", iv.phase), turn=result.get("turn", iv.turn_count),
        interview_id=iv.id, outcome=iv.outcome, tactic=result.get("tactic"),
        trace=result.get("trace"),
    )


def _persist_turn(db: Session, iv: Interview, agent: InterrogationAgent,
                  result: dict, body: ChatRequest, is_silence: bool) -> None:
    """Write this turn's rows and the engine snapshot. Caller holds the lock."""
    stage = result.get("stage", iv.phase)
    seq = len(iv.turns)

    if not is_silence:
        db.add(Turn(interview_id=iv.id, seq=seq, role="user", text=body.message,
                    modality=body.modality, addressed_to="learner", phase=stage))
        seq += 1

    utterances = result.get("utterances", [])
    # An aside is one exchange with two speakers. Sharing an exchange_id keeps
    # them grouped while leaving each line separately analysable.
    exchange = str(uuid.uuid4()) if len(utterances) > 1 else None
    # The decision trace belongs to the exchange, not to each line - store it once,
    # on the first agent row, so the trace endpoint reads exactly one per turn.
    for i, u in enumerate(utterances):
        db.add(Turn(interview_id=iv.id, seq=seq, role="agent",
                    agent_name=u.get("speaker"), text=u.get("text", ""),
                    modality="synthesised", addressed_to=u.get("addressed_to", "learner"),
                    exchange_id=exchange, tactic=result.get("tactic"),
                    phase=stage, turn_number=result.get("turn"),
                    emotion=u.get("emotion"),
                    decision_trace=result.get("trace") if i == 0 else None))
        seq += 1

    # Sync the structured claims the post-session assessment reads. Keyed by
    # claim id, not text: a claim is superseded or restated on a LATER turn than
    # it was created, so an insert-only, text-deduped write never recorded those
    # mutations - the table showed every claim as live, first-time and unlinked.
    # Upsert instead: update the row's mutable fields if it exists, else insert.
    existing = {row.id: row for row in iv.claims}
    for c in agent.state.claims:
        row = existing.get(c.id)
        if row is None:
            db.add(_claim_row(iv.id, c))
        else:
            row.superseded_by = c.superseded_by
            row.restates = c.restates
            row.vouched_by_chen = 1 if c.vouched_by_chen else 0
            row.topic = c.topic

    # Persist the whole engine so the interview resumes exactly as left.
    iv.engine_state = agent.state.to_dict()
    iv.turn_count = agent.state.turn
    iv.player_name = agent.player_name
    iv.last_agent = agent.state.last_speaker or iv.last_agent
    iv.phase = stage
    iv.outcome = result.get("outcome")
    if iv.outcome:
        iv.status = "completed"


def _claim_row(interview_id: str, c) -> ClaimRow:
    # `inferred` records whether the learner gave a FULL span or a partial one:
    # a claim missing a bound is one the timeline fills in, and the assessment
    # must know a bound was invented rather than stated. It is derived from the
    # raw claim here - the runtime `inferred` flag lives only on the normalised
    # copies the timeline builds, never on the stored claim.
    return ClaimRow(
        id=c.id, interview_id=interview_id, turn_seq=c.turn_seq, text=c.text,
        start_min=c.start_min, end_min=c.end_min, location=c.location,
        place=c.place, activity=c.activity, people=c.people, topic=c.topic,
        superseded_by=c.superseded_by, restates=c.restates,
        inferred=1 if (c.start_min is None or c.end_min is None) else 0,
        vouched_by_chen=1 if c.vouched_by_chen else 0,
        episodic=1 if c.episodic else 0)
