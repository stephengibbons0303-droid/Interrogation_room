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

from agent import InterrogationAgent
from auth import get_current_user
from db import Interview, Turn, User, get_db

router = APIRouter(prefix="/interviews", tags=["interviews"])

# Cap the cache so a long-running server with many learners cannot grow without
# bound. Evicted agents are rebuilt from the database on next use.
_MAX_CACHED_AGENTS = 64
_agents: "OrderedDict[str, InterrogationAgent]" = OrderedDict()
_lock = threading.Lock()


def _hydrate(interview: Interview) -> InterrogationAgent:
    """Rebuild an agent's working state from persisted rows."""
    history = []
    for t in interview.turns:
        if t.role == "user":
            history.append({"role": "user", "content": t.text})
        else:
            history.append({"role": "assistant", "content": t.text,
                            "agent": t.agent_name or "Reynolds"})
    return InterrogationAgent(
        interview_id=interview.id,
        history=history,
        turn_count=interview.turn_count,
        player_name=interview.player_name,
        last_agent=interview.last_agent,
        escalation_score=interview.escalation_score,
        contradiction_count=interview.contradiction_count,
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


class TurnOut(BaseModel):
    seq: int
    role: str
    agent_name: Optional[str] = None
    text: str
    modality: Optional[str] = None
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


class ChatResponse(BaseModel):
    text: str
    agent: str
    emotion: Optional[str] = None
    phase: str
    turn: int
    interview_id: str


def _summary(iv: Interview) -> InterviewSummary:
    first_user = next((t.text for t in iv.turns if t.role == "user"), None)
    return InterviewSummary(
        id=iv.id, status=iv.status, phase=iv.phase, turn_count=iv.turn_count,
        player_name=iv.player_name,
        created_at=iv.created_at.isoformat() if iv.created_at else None,
        updated_at=iv.updated_at.isoformat() if iv.updated_at else None,
        preview=(first_user[:80] if first_user else None),
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
    iv = Interview(user_id=user.id)
    db.add(iv)
    db.commit()
    db.refresh(iv)
    return _summary(iv)


@router.get("/{interview_id}", response_model=InterviewDetail)
def get_interview(interview_id: str, user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    iv = _owned(interview_id, user, db)
    detail = InterviewDetail(**_summary(iv).model_dump())
    detail.turns = [
        TurnOut(seq=t.seq, role=t.role, agent_name=t.agent_name, text=t.text,
                modality=t.modality, phase=t.phase, emotion=t.emotion)
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
    agent = get_agent(iv)

    is_silence = body.message.strip() == "[SILENCE]"
    result = agent.process_message(body.message)

    seq = len(iv.turns)
    if not is_silence:
        db.add(Turn(interview_id=iv.id, seq=seq, role="user", text=body.message,
                    modality=body.modality, phase=result.get("phase")))
        seq += 1

    db.add(Turn(interview_id=iv.id, seq=seq, role="agent",
                agent_name=result.get("agent"), text=result.get("text", ""),
                modality="synthesised", phase=result.get("phase"),
                turn_number=result.get("turn"), emotion=result.get("emotion")))

    # Persist the agent's working state so this interview can be resumed.
    iv.turn_count = agent.turn_count
    iv.player_name = agent.player_name
    iv.last_agent = agent.last_agent
    iv.escalation_score = agent.escalation_score
    iv.contradiction_count = agent.contradiction_count
    iv.phase = result.get("phase", iv.phase)
    db.commit()

    return ChatResponse(
        text=result.get("text", ""), agent=result.get("agent", "Reynolds"),
        emotion=result.get("emotion"), phase=result.get("phase", iv.phase),
        turn=result.get("turn", iv.turn_count), interview_id=iv.id,
    )
