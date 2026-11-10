from datetime import timedelta

from conftest import insert
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.main import create_app
from app.models import Job, VectorChange, now
from app.provider import ProviderFailure, StubProvider

P = "/api/v1"


def test_full_restart_and_privacy(cfg):
    with TestClient(create_app(cfg)) as c:
        cid = c.post(P + "/conversations", json={}).json()["id"]
        for t in [
            "I prefer detailed explanations.",
            "I struggled with thermodynamics yesterday.",
            "My physics quiz is on November 19, 2026.",
        ]:
            assert c.post(P + "/chat", json={"conversation_id": cid, "content": t}).status_code == 200
        suggestion = c.get(P + "/calendar/candidates").json()[0]
        c.post(P + "/calendar/candidates/" + suggestion["id"] + "/confirm")
        c.post(P + "/settings", json={})
        response = c.post(
            P + "/chat", json={"conversation_id": cid, "content": "Show all my upcoming deadlines."}
        ).json()
        assert "Physics quiz" in response["assistant"]["content"]
        assert c.get(P + "/memory/episodes").json() and c.get(P + "/memory/semantic").json()
        c.patch(P + "/conversations/" + cid, json={"closed": True, "title": "Saved session"})
    with TestClient(create_app(cfg)) as c:
        assert c.get(P + "/conversations/" + cid).json()["title"] == "Saved session"
        assert len(c.get(P + "/conversations/" + cid + "/messages").json()) == 8
        assert c.get(P + "/memory/short-term?conversation_id=" + cid).json()
        assert (
            c.get(P + "/persona").json()["profile"]["learning_preferences"]["explanation_depth"]
            == "detailed explanations"
        )
        assert c.get(P + "/calendar/events").json()[0]["local_date"] == "2026-11-19"
        assert c.post(P + "/chat", json={"conversation_id": cid, "content": "closed"}).status_code == 409
        assert c.delete(P + "/conversations/" + cid).status_code == 204
        for route in [
            "conversations",
            "memory/episodes",
            "memory/semantic",
            "persona/history",
            "calendar/events",
            "calendar/candidates",
            "jobs",
        ]:
            assert not c.get(P + "/" + route).json()
        assert c.get(P + "/data/export").json()["messages"] == []
        with c.app.state.db.sessions() as s:
            assert not list(s.scalars(select(VectorChange)))


def test_delete_shared_evidence_and_cited_replies(client, cid):
    c2 = client.post(P + "/conversations", json={"title": "Another session"}).json()["id"]
    for c in (cid, c2):
        insert(client, c, "I am studying mechanical engineering.", now() - timedelta(minutes=5))
    client.post(
        P + "/chat",
        json={"conversation_id": c2, "content": "What do you know about my engineering studies?"},
    )
    client.delete(P + "/conversations/" + cid)
    assert client.get(P + "/memory/semantic").json() == []
    assert all(m["role"] == "user" for m in client.get(f"{P}/conversations/{c2}/messages").json())


def test_jobs_retry_and_recovery(cfg):
    class Failure(StubProvider):
        def analyze(self, message):
            raise ProviderFailure("provider failure")

    with TestClient(create_app(cfg, Failure())) as c:
        cid = c.post(P + "/conversations", json={}).json()["id"]
        insert(c, cid, "I practiced probability.")
        job = c.get(P + "/jobs").json()[0]
        for _ in range(3):
            with c.app.state.db.write() as s:
                s.get(Job, job["id"]).available_at = now()
            c.app.state.memory.run_one()
        item = c.get(P + "/jobs/" + job["id"]).json()
        assert item["status"] == "failed" and item["attempts"] == 3
        assert (
            c.get(f"{P}/conversations/{cid}/messages").json()[0]["content"] == "I practiced probability."
        )
        c.post(P + "/jobs/" + job["id"] + "/retry")
        with c.app.state.db.write() as s:
            s.get(Job, job["id"]).status = "running"
    with TestClient(create_app(cfg, StubProvider())) as c:
        assert c.get(P + "/jobs/" + job["id"]).json()["status"] == "queued"
        c.app.state.memory.run_one()
        assert c.get(P + "/jobs/" + job["id"]).json()["status"] == "done"
        assert len(c.get(P + "/memory/episodes").json()) == 1


def test_foreign_origin_and_settings_validation(client):
    assert (
        client.post(P + "/conversations", headers={"Origin": "https://example.org"}, json={}).status_code
        == 403
    )
    assert client.patch(P + "/settings", json={"timezone": "unknown/zone"}).status_code == 422
    assert client.patch(P + "/settings", json={"max_messages": 0}).status_code == 422
    assert client.delete(P + "/data?confirm=oops").status_code == 422
    assert "KEY" not in client.get(P + "/settings").text


def test_weekly_chat_range_and_settings(client, cid):
    client.post(P + "/calendar/events", json={"title": "Physics assignment", "date": "2026-11-14"})
    client.post(P + "/calendar/events", json={"title": "Other assignment", "date": "2026-11-21"})
    from conftest import FIXED

    with client.app.state.db.sessions() as s:
        rows = client.app.state.memory.calendar_answer(
            s, "Which assignments do I have this week?", FIXED
        )
    assert [r["title"] for r in rows] == ["Physics assignment"]
