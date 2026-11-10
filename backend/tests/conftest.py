from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.contracts import Turn
from app.main import create_app
from app.models import Conversation

FIXED = datetime(2026, 11, 10, 4, 30, tzinfo=UTC)


@pytest.fixture
def cfg(tmp_path):
    return Config(
        db_url="sqlite:///" + (tmp_path / "workspace.db").as_posix(),
        chroma_dir=tmp_path / "chroma",
        worker=False,
        vector_enabled=False,
        llm_enabled=False,
        llm_model="",
    )


@pytest.fixture
def client(cfg):
    with TestClient(create_app(cfg)) as api:
        yield api


@pytest.fixture
def cid(client):
    return client.post("/api/v1/conversations", json={"title": "Mechanics"}).json()["id"]


def insert(client, cid, text, at=FIXED):
    with client.app.state.db.write() as s:
        return client.app.state.memory.ingest(s, s.get(Conversation, cid), Turn(content=text), at=at).id
