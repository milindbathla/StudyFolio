"""Local application commands. Run from the editable install or backend directory."""

import argparse
import os
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from .config import Config, data_dir
from .contracts import Query, Review, Turn
from .db import Database
from .memory import working
from .memory.orchestrator import MemoryOrchestrator
from .models import Candidate, Conversation, Message
from .provider import Provider
from .vectors import VectorIndex


def demo_config():
    folder = data_dir() / "synthetic-demo"
    return Config(
        db_url="sqlite:///" + (folder / "demo.db").as_posix(),
        chroma_dir=folder / "chroma",
        llm_enabled=False,
        llm_model="",
    )


SCENES = [
    (
        "Academic background",
        [
            "I am studying mechanical engineering.",
            "I am interested in machine learning and programming.",
        ],
    ),
    (
        "Explanation preferences",
        [
            "I prefer short explanations.",
            "Actually, I now prefer detailed explanations with mathematical derivations.",
        ],
    ),
    (
        "Rotational dynamics",
        ["I struggled with rotational dynamics yesterday.", "My goal is to prepare for examinations."],
    ),
    ("Mechanics assignment", ["My mechanics assignment is due on November 18, 2026."]),
    ("Deadline extension", ["Actually, the assignment deadline has been moved to November 20, 2026."]),
    ("Preference recall", ["What do you remember about my study preferences?"]),
]


def seed(cfg):
    from sqlalchemy import select

    from .calendar.service import confirm

    db = Database(cfg)
    db.initialize()
    orch = MemoryOrchestrator(db, cfg, VectorIndex(cfg), Provider(cfg))
    start = datetime(2026, 11, 6, 5, 0, tzinfo=UTC)
    with db.write() as s:
        for index, (title, turns) in enumerate(SCENES):
            cid = str(uuid5(NAMESPACE_URL, "studyfolio-synthetic-session/" + str(index)))
            c = s.get(Conversation, cid)
            if not c:
                c = Conversation(
                    id=cid,
                    title=title,
                    synthetic=True,
                    created_at=start + timedelta(hours=index),
                    updated_at=start + timedelta(hours=index),
                )
                s.add(c)
                s.flush()
            for n, content in enumerate(turns):
                at = start + timedelta(hours=index, minutes=n * 5)
                key = f"demo-v1-{index}-{n}"
                m = orch.ingest(s, c, Turn(content=content, request_key=key), at)
                if index == 5 and not s.scalar(
                    select(Message.id).where(
                        Message.conversation_id == c.id,
                        Message.role == "assistant",
                        Message.request_key == key,
                    )
                ):
                    ctx = orch.search(s, Query(query=content, conversation_id=c.id), at)
                    working.add_message(
                        s,
                        c,
                        "assistant",
                        orch.offline_reply(content, ctx),
                        at + timedelta(seconds=1),
                        key,
                        {"mode": "offline", "sources": ctx["selected"]},
                    )
                if index in (3, 4):
                    p = s.scalar(select(Candidate).where(Candidate.source_id == m.id))
                    if p and p.status == "proposed":
                        confirm(s, p, Review())
    db.engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="Studyfolio local workspace")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("serve")
    run.add_argument("--demo", action="store_true", help="Open the separate synthetic workspace")
    sub.add_parser("migrate", help="Upgrade the local SQLite schema")
    sub.add_parser("demo", help="Seed the separate deterministic synthetic workspace")
    sub.add_parser("cache-model", help="Download the configured public embedding model once")
    args = parser.parse_args()
    if args.command == "demo":
        cfg = demo_config()
        seed(cfg)
        print("Six synthetic conversations seeded. Start with: python -m app.cli serve --demo")
    elif args.command == "migrate":
        db = Database(Config())
        db.initialize()
        db.engine.dispose()
        print("Local database upgraded.")
    elif args.command == "cache-model":
        from huggingface_hub import snapshot_download

        cfg = Config()
        snapshot_download(
            repo_id=cfg.embedding_model,
            allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "*.py", "*/config.json"],
        )
        print("Embedding model cached locally.")
    else:
        import uvicorn

        from .main import create_app

        uvicorn.run(
            create_app(demo_config() if args.demo else Config()),
            host=os.getenv("APP_HOST", "127.0.0.1"),
            port=int(os.getenv("APP_PORT", "8000")),
            access_log=False,
            log_level=os.getenv("LOG_LEVEL", "INFO").lower(),
        )


if __name__ == "__main__":
    main()
