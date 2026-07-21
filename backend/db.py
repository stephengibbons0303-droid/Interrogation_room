"""Database models and session handling.

SQLite locally, Postgres in Azure - set DATABASE_URL to switch. SAIF uses the
same SQLAlchemy + DATABASE_URL arrangement, so sharing its Postgres resource
later is a connection-string change rather than a rewrite.

Ids are string UUIDs rather than autoincrement integers so they behave
identically on both backends and stay stable if rows are ever moved between
them.
"""
import os
import uuid
from datetime import datetime, timezone

from sqlalchemy import (Column, DateTime, ForeignKey, Integer, String, Text,
                        create_engine)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./interrogation.db")

# check_same_thread is a SQLite-only concern: the HTTP server touches the DB
# from multiple worker threads.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    # Mirrors SAIF's user shape so a SAIF-issued token maps cleanly onto a
    # local user when the SimDeck handshake is built.
    role = Column(String(50), nullable=False, default="learner")
    saif_user_id = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=_now)

    interviews = relationship("Interview", back_populates="user",
                              cascade="all, delete-orphan")


class Interview(Base):
    """One interrogation session - resumable, and the unit of assessment.

    The agent's working state lives here rather than in memory so a learner can
    dip out and pick the same interview back up, and so nothing is lost when the
    server restarts.
    """
    __tablename__ = "interviews"

    id = Column(String(36), primary_key=True, default=_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)

    status = Column(String(20), nullable=False, default="active")  # active | completed
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    # Rehydratable agent state
    turn_count = Column(Integer, nullable=False, default=0)
    player_name = Column(String(255), nullable=True)
    last_agent = Column(String(50), nullable=False, default="Reynolds")
    phase = Column(String(50), nullable=False, default="ORIENTATION")
    escalation_score = Column(Integer, nullable=False, default=0)
    contradiction_count = Column(Integer, nullable=False, default=0)

    user = relationship("User", back_populates="interviews")
    turns = relationship("Turn", back_populates="interview",
                         cascade="all, delete-orphan",
                         order_by="Turn.seq")


class Turn(Base):
    """A single utterance, learner or detective.

    This table is the substrate for the post-session KLP assessment, so it
    records more than the UI needs today.

    `modality` is the one field that cannot be reconstructed later: a typed
    answer is not evidence of speaking proficiency, and credit for listening
    attaches to the detective question the learner demonstrably understood.
    Capture it at the moment of the turn or lose the distinction permanently.
    """
    __tablename__ = "turns"

    id = Column(String(36), primary_key=True, default=_uuid)
    interview_id = Column(String(36), ForeignKey("interviews.id"),
                          nullable=False, index=True)
    seq = Column(Integer, nullable=False)

    role = Column(String(20), nullable=False)          # user | agent
    agent_name = Column(String(50), nullable=True)     # Reynolds | Chen | System
    text = Column(Text, nullable=False)

    # spoken | typed  (learner turns) · synthesised (detective turns)
    modality = Column(String(20), nullable=True)

    phase = Column(String(50), nullable=True)
    turn_number = Column(Integer, nullable=True)
    emotion = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=_now)

    interview = relationship("Interview", back_populates="turns")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency - one DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
