from datetime import timedelta

from conftest import FIXED, insert
from fastapi.testclient import TestClient

from app.contracts import FactProposal, PatchProposal, Query, Reflection
from app.main import create_app
from app.memory import extraction
from app.models import Message, now
from app.provider import StubProvider

P = "/api/v1"


def test_working_window_and_history(client, cid):
    at = now()
    insert(client, cid, "old turn", at - timedelta(days=3))
    insert(client, cid, "first turn", at - timedelta(minutes=2))
    insert(client, cid, "second turn", at - timedelta(minutes=1))
    client.patch(P + "/settings", json={"max_messages": 1})
    assert [m["content"] for m in client.get(P + "/memory/short-term").json()] == ["second turn"]
    assert len(client.get(f"{P}/conversations/{cid}/messages").json()) == 3
    client.delete(P + "/memory/short-term/" + cid)
    assert not client.get(P + "/memory/short-term").json()
    assert len(client.get(f"{P}/conversations/{cid}/messages").json()) == 3


def test_duplicate_evidence_and_explicit_correction(client, cid):
    for txt in [
        "I prefer short explanations.",
        "I prefer short explanations.",
        "Actually, I now prefer detailed explanations.",
    ]:
        insert(client, cid, txt)
    rows = client.get(P + "/memory/semantic").json()
    assert len(rows) == 2
    old = next(x for x in rows if x["status"] == "superseded")
    assert len(old["evidence"]) == 2 and old["superseded_by"]
    profile = client.get(P + "/persona").json()
    assert profile["profile"]["learning_preferences"]["explanation_depth"] == "detailed explanations"
    assert len(client.get(P + "/persona/history").json()) >= 3


def test_scoped_preference_and_manual_protection(client, cid):
    insert(client, cid, "I prefer brief explanations.")
    insert(client, cid, "For technical topics, I now prefer detailed explanations.")
    active = client.get(P + "/memory/semantic?status=active").json()
    assert len(active) == 2 and {m["scope"] for m in active} == {"", "technical topics"}
    original = next(x for x in client.get(P + "/persona").json()["assertions"] if not x["scope"])
    client.patch(
        P + "/persona",
        json={
            "operation": "REPLACE",
            "path": original["path"],
            "target_id": original["id"],
            "value": "mathematical derivations",
        },
    )
    insert(client, cid, "Actually, I now prefer short explanations.", now())
    result = client.get(P + "/persona").json()
    assert result["profile"]["learning_preferences"]["explanation_depth"] == "mathematical derivations"
    assert any(a["status"] == "pending" for a in result["assertions"])


def test_inferred_rejection_cannot_reappear(client, cid):
    mid = insert(client, cid, "I asked for diagrams.")
    p = FactProposal(
        path="learning_preferences.preferred_examples",
        value="diagrams",
        message_id=mid,
        quote="I asked for diagrams.",
        origin="inferred",
        confidence=0.67,
    )
    with client.app.state.db.write() as s:
        a = client.app.state.memory.accept(s, p, s.get(Message, mid))
        assert a.status == "pending"
        aid = a.id
    assert client.post(f"{P}/persona/assertions/{aid}/reject").json()["status"] == "rejected"
    with client.app.state.db.write() as s:
        assert client.app.state.memory.accept(s, p, s.get(Message, mid)) is None
    assert not client.get(P + "/persona").json()["profile"]["learning_preferences"]["preferred_examples"]


def test_grounding_safety_and_low_confidence(client, cid):
    mid = insert(client, cid, "I asked about statistics.")
    with client.app.state.db.sessions() as s:
        m = s.get(Message, mid)
        base = dict(
            path="interests.academic",
            quote=m.content,
            value="statistics",
            message_id=mid,
            confidence=0.8,
        )
        assert extraction.grounded(FactProposal(**base), m)
        for patch in [
            {"quote": "not present"},
            {"value": "medicine"},
            {"confidence": 0.1},
            {"message_id": "wrong"},
        ]:
            assert not extraction.grounded(FactProposal(**(base | patch)), m)
    assert not client.get(P + "/memory/semantic").json()


def test_episode_segmentation_and_historical_retrieval(client, cid):
    insert(client, cid, "I struggled with rotational dynamics.", FIXED - timedelta(days=5))
    insert(
        client,
        cid,
        "I struggled with rotational dynamics examples.",
        FIXED - timedelta(days=5, minutes=-5),
    )
    insert(client, cid, "I practiced probability.", FIXED)
    eps = client.get(P + "/memory/episodes").json()
    assert len(eps) == 2
    assert len(next(e for e in eps if e["event_type"] == "difficulty")["evidence"]) == 2
    with client.app.state.db.sessions() as s:
        output = client.app.state.memory.search(
            s, Query(query="What did I struggle with last week?", layer="episodic"), FIXED
        )
        assert len(output["selected"]) == 1 and "rotational" in output["selected"][0]["content"]


def test_context_budget_and_session_preference(client, cid):
    at = now()
    insert(client, cid, "We were discussing the equation F = ma.", at - timedelta(minutes=1))
    alt = client.post(P + "/conversations", json={}).json()["id"]
    insert(client, alt, "An unrelated equation from another course.", at)
    q = {"query": "What was the equation we were discussing?", "conversation_id": cid}
    hit = client.post(P + "/memory/search", json=q).json()["selected"][0]
    assert hit["layer"] == "working" and "F = ma" in hit["content"]
    out = client.post(P + "/memory/search", json=q | {"budget": 16}).json()
    assert out["tokens"] <= 16 and any(x["reason"] == "context budget" for x in out["excluded"])


def test_edit_reject_restore_and_delete(client, cid):
    mid = insert(client, cid, "I have completed introductory programming.")
    mem = client.get(P + "/memory/semantic").json()[0]
    assert client.get(P + "/memory/" + mem["id"] + "/evidence").json()[0]["message_id"] == mid
    changed = client.patch(
        P + "/memory/semantic/" + mem["id"], json={"value": "advanced programming"}
    ).json()
    assert changed["value"] == "advanced programming"
    a = next(
        x for x in client.get(P + "/persona").json()["assertions"] if x["semantic_id"] == changed["id"]
    )
    assert client.post(f"{P}/persona/assertions/{a['id']}/reject").json()["status"] == "rejected"
    assert client.post(f"{P}/persona/assertions/{a['id']}/confirm").json()["status"] == "active"
    assert client.delete(P + "/memory/semantic/" + mem["id"]).status_code == 204
    client.post(f"{P}/conversations/{cid}/reprocess")
    while client.app.state.memory.run_one():
        pass
    assert all(
        x["value"] != "introductory programming" for x in client.get(P + "/memory/semantic").json()
    )


def test_structured_reflection_and_failures(cfg):
    stub = StubProvider()
    with TestClient(create_app(cfg, stub)) as client:
        cid = client.post(P + "/conversations", json={}).json()["id"]
        mid = insert(client, cid, "I use concept maps for lectures.")
        stub.reflection = Reflection(
            patches=[
                PatchProposal(
                    path="learning_preferences.preferred_learning_style",
                    value="concept maps",
                    quote="I use concept maps for lectures.",
                    message_id=mid,
                    origin="inferred",
                    confidence=0.78,
                    operation="ADD",
                )
            ]
        )
        client.post(f"{P}/conversations/{cid}/reflect")
        while client.app.state.memory.run_one():
            pass
        assert len(stub.calls) == 2
        result = client.get(P + "/persona").json()["assertions"]
        assert (
            len(result) == 1
            and result[0]["status"] == "pending"
            and result[0]["evidence"][0]["message_id"] == mid
        )
        assert (
            client.post(
                P + "/chat", json={"conversation_id": cid, "content": "What do you recall?"}
            ).json()["assistant"]["details"]["mode"]
            == "model"
        )


def test_request_idempotency_and_search(client, cid):
    body = {
        "conversation_id": cid,
        "content": "I prefer detailed explanations.",
        "request_key": "unique-key",
    }
    a = client.post(P + "/chat", json=body).json()
    b = client.post(P + "/chat", json=body).json()
    assert a["assistant"]["id"] == b["assistant"]["id"]
    assert len(client.get(f"{P}/conversations/{cid}/messages").json()) == 2
    assert client.post(P + "/chat", json=body | {"content": "different"}).status_code == 409
    assert client.get(P + "/conversations?q=detailed").json()[0]["id"] == cid
