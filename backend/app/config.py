import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
USER = "00000000-0000-4000-8000-000000000001"


def data_dir():
    base = Path(
        os.getenv("LOCALAPPDATA") or os.getenv("XDG_DATA_HOME") or Path.home() / ".local" / "share"
    )
    return Path(os.getenv("APP_DATA_DIR") or base / "Studyfolio").resolve()


def flag(key, default):
    return os.getenv(key, str(default)).lower() in {"true", "1", "yes"}


def defaults():
    return dict(
        timezone=os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata"),
        max_messages=int(os.getenv("SHORT_TERM_MAX_MESSAGES", 30)),
        max_tokens=int(os.getenv("SHORT_TERM_MAX_TOKENS", 4000)),
        window_hours=int(os.getenv("SHORT_TERM_HOURS", 24)),
        reflection_threshold=int(os.getenv("MEMORY_REFLECTION_MESSAGE_THRESHOLD", 8)),
        require_confirmation=flag("CALENDAR_REQUIRE_CONFIRMATION", True),
        auto_explicit=flag("CALENDAR_AUTO_CONFIRM_EXPLICIT_COMMANDS", True),
    )


@dataclass
class Config:
    db_url: str = field(
        default_factory=lambda: (
            os.getenv("DATABASE_URL")
            or "sqlite:///" + (data_dir() / "sqlite" / "learner_memory.db").as_posix()
        )
    )
    chroma_dir: Path = field(
        default_factory=lambda: (
            ROOT / os.getenv("CHROMA_PERSIST_DIR")
            if os.getenv("CHROMA_PERSIST_DIR")
            else data_dir() / "chroma"
        )
    )
    vector_enabled: bool = field(default_factory=lambda: flag("VECTOR_ENABLED", True))
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    )
    embedding_device: str = field(default_factory=lambda: os.getenv("EMBEDDING_DEVICE", "cpu"))
    llm_enabled: bool = field(default_factory=lambda: flag("LLM_ENABLED", False))
    llm_model: str = field(default_factory=lambda: os.getenv("LLM_MODEL", "").strip())
    worker: bool = True
    ranking: dict = field(
        default_factory=lambda: {
            "lexical": 0.50,
            "vector": 0.27,
            "confidence": 0.09,
            "explicit": 0.06,
            "importance": 0.05,
            "recency": 0.03,
        }
    )

    def __post_init__(self):
        if not self.db_url.startswith("sqlite:///"):
            raise ValueError("The local application requires a SQLite database.")
        if self.db_url.startswith("sqlite:///./"):
            self.db_url = "sqlite:///" + (ROOT / self.db_url[10:]).as_posix()
        ZoneInfo(defaults()["timezone"])
