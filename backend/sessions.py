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
from sqlalchemy.orm import Session

import uuid

from agent import InterrogationAgent
from auth import get_current_user
from db import Claim as ClaimRow, Interview, Turn, User, get_db
from engine.state import InterviewState
from scenario import briefs as briefs_mod

router = APIRouter(prefix="/interviews", tags=["interviews"])

# Cap the cache so a long-running server with many learners cannot grow without
# bound. Evicted agents are rebuilt from the database on next use.
_MAX_CACHED_AGENTS = 64
_agents: "OrderedDict[str, InterrogationAgent]" = OrderedDict()
_lock = threading.Lock()


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


class BriefFactOut(BaseModel):
    text: str


class BriefOut(BaseModel):
    """The learner's own brief. Deliberately shown to them - holding it in a
    second language under pressure is the game; memorising it is not."""
    id: str
    premise: str
    facts: List[BriefFactOut]
    conceal: Optional[str] = None
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
    rows = (db.query(Interview)
              .filter(Interview.user_id == user.id)
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
        facts=[BriefFactOut(text=f.text) for f in brief.facts],
        conceal=brief.conceal, awkward=brief.awkward,
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
    iv = _owned(interview_id, user, db)
    if iv.outcome:
        raise HTTPException(status_code=409, detail="This interview has concluded")

    agent = get_agent(iv)
    is_silence = body.message.strip() == "[SILENCE]"
    result = agent.process_message(body.message)

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
    for u in utterances:
        db.add(Turn(interview_id=iv.id, seq=seq, role="agent",
                    agent_name=u.get("speaker"), text=u.get("text", ""),
                    modality="synthesised", addressed_to=u.get("addressed_to", "learner"),
                    exchange_id=exchange, tactic=result.get("tactic"),
                    phase=stage, turn_number=result.get("turn"),
                    emotion=u.get("emotion")))
        seq += 1

    # New structured claims, for the post-session assessment.
    known = {c.text for c in iv.claims}
    for c in agent.state.claims:
        if c.text in known:
            continue
        db.add(ClaimRow(id=c.id, interview_id=iv.id, turn_seq=c.turn_seq,
                        text=c.text, start_min=c.start_min, end_min=c.end_min,
                        location=c.location, activity=c.activity,
                        superseded_by=c.superseded_by,
                        vouched_by_chen=1 if c.vouched_by_chen else 0))

    # Persist the whole engine so the interview resumes exactly as left.
    iv.engine_state = agent.state.to_dict()
    iv.turn_count = agent.state.turn
    iv.player_name = agent.player_name
    iv.last_agent = agent.state.last_speaker or iv.last_agent
    iv.phase = stage
    iv.outcome = result.get("outcome")
    if iv.outcome:
        iv.status = "completed"
    db.commit()

    return ChatResponse(
        utterances=[UtteranceOut(**u) for u in utterances],
        phase=stage, turn=result.get("turn", iv.turn_count),
        interview_id=iv.id, outcome=iv.outcome, tactic=result.get("tactic"),
    )
