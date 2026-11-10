from datetime import date
from datetime import time as ClockTime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=250)]
Value = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=600)]
Category = Literal["assignment", "exam", "quiz", "project", "registration", "meeting", "milestone"]
Operation = Literal["ADD", "REPLACE", "REMOVE", "SUPERSEDE", "NO_CHANGE"]
FIELDS = {
    "identity": ("name", "institution", "degree", "branch", "academic_year"),
    "academic_profile": (
        "current_courses",
        "completed_courses",
        "topics_studied",
        "reported_strengths",
        "reported_difficulties",
    ),
    "goals": ("short_term", "long_term", "active_projects"),
    "learning_preferences": (
        "explanation_depth",
        "preferred_learning_style",
        "preferred_examples",
        "language_preferences",
    ),
    "behavioral_patterns": (
        "study_routines",
        "recurring_learning_behaviors",
        "common_requests",
        "observed_patterns",
    ),
    "constraints": ("time_constraints", "academic_deadlines", "other_constraints"),
    "interests": ("academic", "technical", "other"),
}
PATHS = {f"{section}.{key}" for section, keys in FIELDS.items() for key in keys}
SCALARS = {p for p in PATHS if p.startswith("identity.")} | {"learning_preferences.explanation_depth"}


def valid_path(path):
    if path not in PATHS:
        raise ValueError("Unknown persona field")
    return path


def valid_zone(name):
    try:
        ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError) as exc:
        raise ValueError("Unknown IANA timezone") from exc
    return name


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SettingsPatch(Contract):
    timezone: str | None = None
    max_messages: int | None = Field(None, ge=1, le=100)
    max_tokens: int | None = Field(None, ge=32, le=16000)
    window_hours: int | None = Field(None, ge=1, le=720)
    reflection_threshold: int | None = Field(None, ge=1, le=100)
    require_confirmation: bool | None = None
    auto_explicit: bool | None = None

    @field_validator("timezone")
    @classmethod
    def zone(cls, value):
        return valid_zone(value) if value else value


class NewThread(Contract):
    title: Short = "Untitled conversation"


class EditThread(Contract):
    title: Short | None = None
    closed: bool | None = None


class Turn(Contract):
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=16000)]
    request_key: Short | None = None


class Chat(Turn):
    conversation_id: Short


class Query(Contract):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    conversation_id: Short | None = None
    layer: Literal["working", "episodic", "semantic", "persona"] | None = None
    start: date | None = None
    end: date | None = None
    budget: int | None = Field(None, ge=16, le=16000)


class FactProposal(Contract):
    path: str
    value: Value
    scope: str = Field("", max_length=90)
    message_id: Short
    quote: Value
    origin: Literal["explicit", "inferred"] = "explicit"
    confidence: float = Field(ge=0, le=1)
    correction: bool = False

    _path = field_validator("path")(valid_path)


class EpisodeProposal(Contract):
    summary: Value
    topic: Short
    kind: Literal["difficulty", "practice", "success", "goal", "deadline", "study"]
    quote: Value
    message_id: Short


class DateHint(Contract):
    title: Short
    category: Category
    date_phrase: Short
    message_id: Short


class Analysis(Contract):
    facts: list[FactProposal] = Field(default_factory=list, max_length=10)
    episodes: list[EpisodeProposal] = Field(default_factory=list, max_length=3)
    dates: list[DateHint] = Field(default_factory=list, max_length=5)


class PatchProposal(FactProposal):
    operation: Operation
    target_id: str | None = None


class Reflection(Contract):
    patches: list[PatchProposal] = Field(default_factory=list, max_length=16)


class ConflictDecision(Contract):
    status: Literal["active", "pending"]
    reason: str


class RelevanceDecision(Contract):
    id: str
    reason: str


class ManualPatch(Contract):
    operation: Operation = "ADD"
    path: str
    value: Value | None = None
    target_id: str | None = None
    scope: str = Field("", max_length=90)
    _path = field_validator("path")(valid_path)

    @model_validator(mode="after")
    def required_fields(self):
        if self.operation in ("REPLACE", "SUPERSEDE", "REMOVE") and not self.target_id:
            raise ValueError("Choose a target assertion")
        if self.operation in ("ADD", "REPLACE", "SUPERSEDE") and not self.value:
            raise ValueError("Enter a value")
        return self


class SemanticEdit(Contract):
    value: Value | None = None
    status: Literal["active", "rejected", "archived"] | None = None


class EventInput(Contract):
    title: Short
    category: Category = "assignment"
    date: date
    time: ClockTime | None = None
    end_time: ClockTime | None = None
    timezone: str | None = None
    description: str = Field("", max_length=3000)

    @field_validator("timezone")
    @classmethod
    def zone(cls, value):
        return valid_zone(value) if value else value

    @model_validator(mode="after")
    def interval(self):
        if self.end_time and (not self.time or self.end_time <= self.time):
            raise ValueError("End time must be after the start on the same day")
        return self


class Review(Contract):
    event: EventInput | None = None
    target_id: str | None = None


class CsvImport(Contract):
    content: str = Field(max_length=500000)


class Rebuild(Contract):
    history: bool = False
