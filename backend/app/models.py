from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .config import USER


def uid():
    return str(uuid4())


def now():
    return datetime.now(UTC)


class Instant(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Expected an aware datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None else None


class Base(DeclarativeBase):
    type_annotation_map = {datetime: Instant(), dict: JSON, list: JSON}


class Row:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Owned(Row):
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), default=USER, index=True
    )


class User(Row, Base):
    __tablename__ = "users"
    name: Mapped[str] = mapped_column(default="Local learner")


class Settings(Owned, Base):
    __tablename__ = "user_settings"
    values: Mapped[dict] = mapped_column(default=dict)
    __table_args__ = (UniqueConstraint("user_id"),)


class Conversation(Owned, Base):
    __tablename__ = "conversations"
    title: Mapped[str]
    synthetic: Mapped[bool] = mapped_column(default=False)
    closed: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(default=now, index=True)
    cleared_at: Mapped[datetime | None]
    reflected_through: Mapped[datetime | None]
    reflected_position: Mapped[int] = mapped_column(default=0, server_default="0")


class Message(Owned, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(default="saved")
    request_key: Mapped[str | None]
    position: Mapped[int] = mapped_column(server_default="0")
    __table_args__ = (
        Index("ix_message_thread_time", "conversation_id", "created_at"),
        Index("uq_message_position", "conversation_id", "position", unique=True),
        UniqueConstraint("conversation_id", "request_key", "role"),
    )


class Memory(Owned, Base):
    __tablename__ = "memories"
    layer: Mapped[str]
    content: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(default="active")
    confidence: Mapped[float]
    origin: Mapped[str] = mapped_column(default="explicit")
    importance: Mapped[float] = mapped_column(default=0.6)
    manual: Mapped[bool] = mapped_column(default=False)
    synthetic: Mapped[bool] = mapped_column(default=False)
    valid_from: Mapped[datetime] = mapped_column(default=now)
    valid_until: Mapped[datetime | None]
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)
    superseded_by: Mapped[str | None] = mapped_column(ForeignKey("memories.id", ondelete="SET NULL"))
    __mapper_args__ = {"polymorphic_on": "layer", "polymorphic_identity": "memory"}
    __table_args__ = (Index("ix_memory_current", "user_id", "layer", "status"),)


class Episode(Memory):
    __tablename__ = "episodes"
    id: Mapped[str] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    start_time: Mapped[datetime]
    end_time: Mapped[datetime]
    event_type: Mapped[str]
    topics: Mapped[list]
    details: Mapped[dict] = mapped_column(default=dict)
    __mapper_args__ = {"polymorphic_identity": "episodic"}


class Semantic(Memory):
    __tablename__ = "semantic_memories"
    id: Mapped[str] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True)
    subject: Mapped[str] = mapped_column(default="learner")
    predicate: Mapped[str] = mapped_column(index=True)
    value: Mapped[str]
    scope: Mapped[str] = mapped_column(default="")
    category: Mapped[str]
    observed_at: Mapped[datetime]
    last_confirmed_at: Mapped[datetime]
    __mapper_args__ = {"polymorphic_identity": "semantic"}


class Assertion(Memory):
    __tablename__ = "persona_assertions"
    id: Mapped[str] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), primary_key=True)
    path: Mapped[str] = mapped_column(index=True)
    value: Mapped[str]
    scope: Mapped[str] = mapped_column(default="")
    semantic_id: Mapped[str | None] = mapped_column(
        ForeignKey("semantic_memories.id", ondelete="CASCADE")
    )
    __mapper_args__ = {"polymorphic_identity": "persona", "inherit_condition": id == Memory.id}


class Evidence(Row, Base):
    __tablename__ = "memory_evidence"
    memory_id: Mapped[str] = mapped_column(ForeignKey("memories.id", ondelete="CASCADE"), index=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    span: Mapped[str]
    __table_args__ = (UniqueConstraint("memory_id", "message_id"),)


class PersonaRevision(Owned, Base):
    __tablename__ = "persona_revisions"
    assertion_id: Mapped[str] = mapped_column(
        ForeignKey("persona_assertions.id", ondelete="CASCADE"), index=True
    )
    operation: Mapped[str]
    detail: Mapped[dict]


class Job(Owned, Base):
    __tablename__ = "memory_processing_jobs"
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(unique=True)
    kind: Mapped[str]
    status: Mapped[str] = mapped_column(default="queued", index=True)
    attempts: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None]
    available_at: Mapped[datetime] = mapped_column(default=now)


class EventFields(Owned):
    title: Mapped[str]
    category: Mapped[str]
    description: Mapped[str] = mapped_column(default="")
    local_date: Mapped[str | None]
    start_utc: Mapped[datetime | None]
    end_utc: Mapped[datetime | None]
    all_day: Mapped[bool] = mapped_column(default=True)
    timezone: Mapped[str]
    importance: Mapped[float] = mapped_column(default=0.85)
    reason: Mapped[str] = mapped_column(default="Manually added")
    original_date_text: Mapped[str] = mapped_column(default="")
    parsed: Mapped[dict] = mapped_column(default=dict)
    confidence: Mapped[float] = mapped_column(default=1)
    synthetic: Mapped[bool] = mapped_column(default=False)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)


class Event(EventFields, Base):
    __tablename__ = "calendar_events"
    status: Mapped[str] = mapped_column(default="confirmed", index=True)
    source_type: Mapped[str] = mapped_column(default="manual")
    source_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    user_confirmed: Mapped[bool] = mapped_column(default=True)
    cancelled_at: Mapped[datetime | None]
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (Index("ix_event_date", "user_id", "local_date"),)


class Candidate(EventFields, Base):
    __tablename__ = "calendar_candidates"
    source_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(default="proposed")
    target_id: Mapped[str | None] = mapped_column(ForeignKey("calendar_events.id", ondelete="SET NULL"))
    event_id: Mapped[str | None] = mapped_column(ForeignKey("calendar_events.id", ondelete="SET NULL"))
    source_key: Mapped[str] = mapped_column(unique=True)
    needs_review: Mapped[bool] = mapped_column(Boolean, default=False)


class EventRevision(Owned, Base):
    __tablename__ = "calendar_event_revisions"
    event_id: Mapped[str] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"))
    operation: Mapped[str]
    snapshot: Mapped[dict]


class VectorChange(Row, Base):
    __tablename__ = "vector_changes"
    memory_id: Mapped[str] = mapped_column(unique=True)
    layer: Mapped[str]
    action: Mapped[str]


class Suppression(Row, Base):
    __tablename__ = "suppressed_evidence"
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    fingerprint: Mapped[str]
    __table_args__ = (UniqueConstraint("message_id", "fingerprint"),)
