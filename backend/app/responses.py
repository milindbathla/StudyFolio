from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .contracts import RelevanceDecision


class Record(BaseModel):
    """Shared fields are typed; layer-specific relational fields are preserved."""

    model_config = ConfigDict(extra="allow")
    id: str
    created_at: datetime


class ThreadRecord(Record):
    title: str
    closed: bool
    synthetic: bool
    updated_at: datetime


class MessageRecord(Record):
    conversation_id: str
    role: Literal["user", "assistant"]
    content: str
    details: dict
    status: str


class Source(BaseModel):
    model_config = ConfigDict(extra="allow")
    message_id: str
    conversation_id: str
    timestamp: datetime
    span: str | None = None


class MemoryRecord(Record):
    layer: Literal["episodic", "semantic", "persona"]
    status: str
    content: str
    origin: Literal["explicit", "inferred"]
    confidence: float = Field(ge=0, le=1)
    synthetic: bool
    evidence: list[Source]


class Hit(BaseModel):
    id: str
    layer: Literal["working", "episodic", "semantic", "persona"]
    content: str
    timestamp: datetime
    reasons: list[str]
    evidence: list[Source]
    score: float


class Inspection(BaseModel):
    query: str
    selected: list[Hit]
    excluded: list[RelevanceDecision]
    tokens: int
    budget: int


class ChatReply(BaseModel):
    user: MessageRecord
    assistant: MessageRecord


class PersonaView(BaseModel):
    profile: dict[str, dict[str, str | list[str] | None]]
    assertions: list[MemoryRecord]


class CalendarRecord(Record):
    title: str
    category: str
    local_date: str | None
    timezone: str
    start_utc: datetime | None
    end_utc: datetime | None
    status: str
    synthetic: bool
    parsed: dict
