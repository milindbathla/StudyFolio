import json
from datetime import timedelta
from pathlib import Path

from alembic.config import Config as MigrationConfig
from conftest import FIXED, insert
from sqlalchemy import inspect, text

from alembic import command
from app.contracts import FactProposal
from app.db import Database
from app.models import Base, Message, now

API = "/api/v1"


def test_upgrade_existing_0001_database_and_reopen(cfg):
    db = Database(cfg)
    migration = MigrationConfig()
    migration.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    with db.engine.begin() as connection:
        migration.attributes["connection"] = connection
        command.upgrade(migration, "0001")
        connection.execute(
            text("INSERT INTO users (id,created_at,name) VALUES (:id,CURRENT_TIMESTAMP,:name)"),
            {"id": "legacy-user", "name": "Retained learner"},
        )
        connection.execute(
            text(
                "INSERT INTO conversations (id,user_id,title,synthetic,closed,created_at,updated_at) VALUES ('legacy','legacy-user','Previous session',0,0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
        for identifier, role in [("z-earlier", "user"), ("a-later", "assistant")]:
            connection.execute(
                text(
                    "INSERT INTO messages (id,user_id,conversation_id,role,content,details,status,created_at) VALUES (:id,'legacy-user','legacy',:role,'Historical turn','{}','saved','2026-01-01 00:00:00')"
                ),
                {"id": identifier, "role": role},
            )
    db.initialize()
    db.initialize()
    with db.engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM alembic_version")) == "0005"
        assert conn.scalar(text("SELECT name FROM users WHERE id='legacy-user'")) == "Retained learner"
        assert conn.execute(text("SELECT id,position FROM messages ORDER BY position")).all() == [
            ("z-earlier", 1),
            ("a-later", 2),
        ]
        assert conn.scalar(text("PRAGMA foreign_keys")) == 1
        assert conn.scalar(text("PRAGMA journal_mode")) == "wal"
        assert conn.scalar(text("PRAGMA integrity_check")) == "ok"
        assert not conn.execute(text("PRAGMA foreign_key_check")).all()
        inspector = inspect(conn)
        for table in Base.metadata.sorted_tables:
            assert {c["name"] for c in inspector.get_columns(table.name)} == {
                c.name for c in table.columns
            }
        assert "memory_search" in inspector.get_table_names()
    db.engine.dispose()


def test_chat_source_timestamps_persist_as_json_strings(client, cid):
    req = {"conversation_id": cid, "content": "I prefer short explanations.", "request_key": "ts-1"}
    assert client.post(API + "/chat", json=req).status_code == 200
    ans = client.post(
        API + "/chat",
        json={"conversation_id": cid, "content": "What are my preferences?", "request_key": "ts-2"},
    ).json()["assistant"]
    with client.app.state.db.engine.connect() as conn:
        raw = conn.scalar(text("SELECT details FROM messages WHERE id=:id"), {"id": ans["id"]})
    saved = json.loads(raw)["sources"]
    assert (
        saved
        and isinstance(saved[0]["timestamp"], str)
        and isinstance(saved[0]["evidence"][0]["timestamp"], str)
    )
    stored = client.get(f"{API}/conversations/{cid}/messages").json()[-1]
    assert stored["details"]["sources"] == saved


def test_explicit_return_to_an_earlier_preference_survives_replay(client, cid):
    phrases = [
        "I prefer brief explanations.",
        "Actually, I now prefer detailed explanations.",
        "Actually, I now prefer brief explanations.",
    ]
    for i, phrase in enumerate(phrases):
        insert(client, cid, phrase, FIXED + timedelta(minutes=i))

    def active():
        return client.get(API + "/persona").json()["profile"]["learning_preferences"][
            "explanation_depth"
        ]

    assert active() == "brief explanations"
    client.post(f"{API}/conversations/{cid}/reprocess")
    while client.app.state.memory.run_one():
        pass
    assert active() == "brief explanations"
    assert len(client.get(API + "/memory/semantic").json()) == 3


def test_repeated_deadline_evidence_does_not_restore_obsolete_date(client, cid):
    for i, phrase in enumerate(
        [
            "My physics quiz is on November 19, 2026.",
            "My physics quiz is on November 19, 2026.",
            "The quiz has been postponed to November 22, 2026.",
        ]
    ):
        insert(client, cid, phrase, FIXED + timedelta(minutes=i))
    pending = client.get(API + "/calendar/candidates").json()
    assert len(pending) == 1
    result = client.post(API + "/calendar/candidates/" + pending[0]["id"] + "/confirm").json()
    assert result["local_date"] == "2026-11-22"
    client.post(f"{API}/conversations/{cid}/reprocess")
    while client.app.state.memory.run_one():
        pass
    assert not client.get(API + "/calendar/candidates").json()
    assert len(client.get(API + "/calendar/events").json()) == 1
    assert (
        len(
            {
                rev["source_id"]
                for rev in client.get(API + "/calendar/events/" + result["id"]).json()["history"]
            }
        )
        == 3
    )


def test_repeated_observation_and_failed_local_extraction(client, cid, monkeypatch):
    second = client.post(API + "/conversations", json={"title": "Second session"}).json()["id"]
    engine = client.app.state.memory
    for index, thread in enumerate((cid, cid, second)):
        mid = insert(client, thread, "I asked for diagrams.", now() + timedelta(microseconds=index))
        p = FactProposal(
            path="behavioral_patterns.common_requests",
            value="diagrams",
            quote="I asked for diagrams.",
            message_id=mid,
            origin="inferred",
            confidence=0.71,
        )
        with engine.db.write() as s:
            a = engine.accept(s, p, s.get(Message, mid))
            assert a.status == ("active" if index == 2 else "pending")

    def fail(*args):
        raise ValueError("Intentional test failure")

    with monkeypatch.context() as ctx:
        ctx.setattr(engine, "process", fail)
        res = client.post(
            f"{API}/conversations/{cid}/messages", json={"content": "I practiced calculus."}
        )
        assert res.status_code == 201 and res.json()["status"] == "queued"
    assert engine.run_one()
    history = client.get(f"{API}/conversations/{cid}/messages").json()
    assert history[-1]["status"] == "processed" and history[-1]["content"] == "I practiced calculus."


def test_timed_reschedule_preserves_clock_duration_and_description(client, cid):
    e = client.post(
        API + "/calendar/events",
        json={
            "title": "Physics quiz",
            "category": "quiz",
            "date": "2026-11-19",
            "time": "09:00",
            "end_time": "10:00",
            "description": "Room 4",
        },
    ).json()
    insert(client, cid, "The physics quiz has been postponed to November 22, 2026.")
    c = client.get(API + "/calendar/candidates").json()[0]
    revised = client.post(API + "/calendar/candidates/" + c["id"] + "/confirm").json()
    assert revised["id"] == e["id"] and revised["description"] == "Room 4"
    assert revised["start_utc"].startswith("2026-11-22T03:30:00")
    assert revised["end_utc"].startswith("2026-11-22T04:30:00")


def test_learner_statement_strengthens_a_matching_hypothesis(client, cid):
    mid = insert(client, cid, "I asked for visual examples.", FIXED)
    p = FactProposal(
        path="learning_preferences.explanation_depth",
        value="visual examples",
        quote="I asked for visual examples.",
        message_id=mid,
        origin="inferred",
        confidence=0.67,
    )
    with client.app.state.db.write() as s:
        first = client.app.state.memory.accept(s, p, s.get(Message, mid))
        assert first.status == "pending"
    insert(client, cid, "I prefer visual examples.", FIXED + timedelta(minutes=1))
    assertions = client.get(API + "/persona").json()["assertions"]
    assert (
        len(assertions) == 1
        and assertions[0]["status"] == "active"
        and assertions[0]["origin"] == "explicit"
    )
    assert len(assertions[0]["evidence"]) == 2


def test_reflection_batches_do_not_drop_turns_with_identical_timestamps(cfg):
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.provider import StubProvider

    stub = StubProvider()
    with TestClient(create_app(cfg, stub)) as c:
        c.patch(API + "/settings", json={"reflection_threshold": 100})
        thread = c.post(API + "/conversations", json={"title": "Tied timestamps"}).json()["id"]
        mids = [insert(c, thread, f"Study note {i}", FIXED) for i in range(20)]
        assert [m["id"] for m in c.get(f"{API}/conversations/{thread}/messages").json()] == mids
        c.post(f"{API}/conversations/{thread}/reflect")
        while c.app.state.memory.run_one():
            pass
        batches = [call["messages"] for call in stub.calls if "messages" in call]
        assert [len(b) for b in batches] == [16, 4]
        assert [m["id"] for batch in batches for m in batch] == mids
