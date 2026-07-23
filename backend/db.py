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
from pathlib import Path

from sqlalchemy import (JSON, Column, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint, create_engine, inspect, text)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

BASE_DIR = Path(__file__).resolve().parent

# Anchored to this file's directory rather than the process working directory.
# A CWD-relative path means starting the server from somewhere else silently
# creates a brand new, empty database - every account and interview appears to
# have vanished, with no error to explain it.
DATABASE_URL = (os.getenv("DATABASE_URL")
                or f"sqlite:///{(BASE_DIR / 'interrogation.db').as_posix()}")

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
    phase = Column(String(50), nullable=False, default="engage")

    # The whole engine state as JSON - pressure, stage, claims, contradictions,
    # evidence disclosure, cooldowns, Chen's stance. See engine/state.py.
    # A blob rather than columns because the shape will keep moving while the
    # engine is tuned, and none of it is queried across interviews.
    engine_state = Column(JSON, nullable=True)

    # Which secret brief this learner was dealt. Denormalised out of
    # engine_state so a session can be picked out by brief without parsing JSON.
    brief_id = Column(String(64), nullable=True)
    outcome = Column(String(32), nullable=True)

    # DEPRECATED: written and never read - pressure and the contradiction ledger
    # live in engine_state now. Not dropped, because a database created before
    # they were retired has them as NOT NULL, and SQLite < 3.35 (Ubuntu 20.04,
    # Debian 11, RHEL 8) cannot DROP COLUMN - so an attempted drop failed and
    # then every new-interview INSERT hit the NOT NULL with no default and 500'd.
    # Keeping them nullable WITH a default is bulletproof across all SQLite and
    # Postgres versions: a fresh schema carries two harmless zero columns, and an
    # old schema's NOT NULL is always satisfied because every insert supplies 0.
    escalation_score = Column(Integer, nullable=True, server_default="0", default=0)
    contradiction_count = Column(Integer, nullable=True, server_default="0", default=0)

    user = relationship("User", back_populates="interviews")
    turns = relationship("Turn", back_populates="interview",
                         cascade="all, delete-orphan",
                         order_by="Turn.seq")
    claims = relationship("Claim", back_populates="interview",
                          cascade="all, delete-orphan")


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

    # One row per (interview, seq). The chat path serialises per interview so seq
    # is assigned without a race, and this makes a double-submit fail loudly
    # rather than silently writing a duplicate that scrambles the replay order.
    __table_args__ = (UniqueConstraint("interview_id", "seq",
                                       name="uq_turns_interview_seq"),)

    role = Column(String(20), nullable=False)          # user | agent
    agent_name = Column(String(50), nullable=True)     # Reynolds | Chen | System
    text = Column(Text, nullable=False)

    # spoken | typed  (learner turns) · synthesised (detective turns)
    modality = Column(String(20), nullable=True)

    # Who the line was aimed at. Detectives conferring in front of the learner
    # ("partner") is a different listening skill from being spoken to directly
    # ("learner"): overheard native dialogue is not simplified for the listener.
    # The assessment needs to credit those separately, and it cannot be
    # reconstructed after the fact.
    addressed_to = Column(String(20), nullable=True, default="learner")
    # Groups the two utterances of an aside into one exchange while keeping each
    # separately analysable.
    exchange_id = Column(String(36), nullable=True, index=True)

    # Which tactic produced this line, for tuning and post-session review.
    tactic = Column(String(50), nullable=True)

    phase = Column(String(50), nullable=True)
    turn_number = Column(Integer, nullable=True)
    emotion = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=_now)

    interview = relationship("Interview", back_populates="turns")


class Claim(Base):
    """A statement the learner committed to, in structured form.

    Mirrors engine.state.Claim, persisted separately from engine_state because
    this is the table the post-session KLP assessment will read: one row per
    committed fact, tied to the turn that produced it.
    """
    __tablename__ = "claims"

    id = Column(String(36), primary_key=True, default=_uuid)
    interview_id = Column(String(36), ForeignKey("interviews.id"),
                          nullable=False, index=True)
    turn_seq = Column(Integer, nullable=False)

    text = Column(Text, nullable=False)
    start_min = Column(Integer, nullable=True)      # minutes past midnight
    end_min = Column(Integer, nullable=True)
    location = Column(String(64), nullable=True)    # one of the four case locations
    place = Column(String(255), nullable=True)      # what they called it, verbatim
    activity = Column(String(255), nullable=True)
    people = Column(JSON, nullable=True)            # names/entities they mentioned
    topic = Column(String(128), nullable=True)      # which thread it belongs to

    # The assessment reads these: a superseded claim is one they withdrew, a
    # restatement ties a second telling to its first, an inferred bound is one
    # the timeline filled in rather than one they stated. Without them the table
    # showed every claim as an independent, live, first-time commitment.
    superseded_by = Column(String(36), nullable=True)
    restates = Column(String(36), nullable=True)
    inferred = Column(Integer, nullable=False, default=0)
    vouched_by_chen = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_now)

    interview = relationship("Interview", back_populates="claims")


# Columns added after the first release. create_all() creates missing *tables*
# but never alters existing ones, so without this an upgraded install keeps the
# old table shape and fails at runtime with a confusing "no such column".
_ADDED_COLUMNS = {
    "interviews": {
        "engine_state": "JSON",
        "brief_id": "VARCHAR(64)",
        "outcome": "VARCHAR(32)",
        # Re-added if missing. A previous build DROPPED these (they were dead),
        # and the model now carries them again as nullable-with-default for
        # forward/backward compatibility - so a database where they were already
        # dropped needs them back, or every insert references a column the table
        # no longer has. Idempotent: skipped where they are already present.
        "escalation_score": "INTEGER DEFAULT 0",
        "contradiction_count": "INTEGER DEFAULT 0",
    },
    "turns": {
        "addressed_to": "VARCHAR(20)",
        "exchange_id": "VARCHAR(36)",
        "tactic": "VARCHAR(50)",
    },
    "claims": {
        "place": "VARCHAR(255)",
        "people": "JSON",
        "topic": "VARCHAR(128)",
        "restates": "VARCHAR(36)",
        "inferred": "INTEGER DEFAULT 0",
    },
}

# Unique indexes to create on existing databases (create_all makes them for
# fresh ones). Wrapped in try/except at apply time: a table already holding
# duplicate rows would reject the index, and that must not block startup.
_ADDED_UNIQUE_INDEXES = {
    "uq_turns_interview_seq": ("turns", ["interview_id", "seq"]),
}


def _ensure_columns() -> None:
    """Bring an existing database up to the current shape. Idempotent.

    Rows are never touched, so a local database keeps its accounts and
    transcripts across the upgrade.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue                       # create_all will build it fresh
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl_type in columns.items():
                if name not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl_type}"))
                    print(f"  db: added {table}.{name}")

        for index_name, (table, cols) in _ADDED_UNIQUE_INDEXES.items():
            if table not in existing_tables:
                continue
            try:
                conn.execute(text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} "
                    f"ON {table} ({', '.join(cols)})"))
            except Exception as e:
                # Existing duplicate rows would reject the index. Skip rather
                # than block startup - the per-interview lock prevents new ones.
                print(f"  db: could not add unique index {index_name} ({e})")


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def get_db():
    """FastAPI dependency - one DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
