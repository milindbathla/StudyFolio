import os

import pytest
from conftest import insert
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import now


def test_offline_index_repair_uses_real_lexical_search(client, cid):
    insert(client, cid, "I have completed introductory programming.", now())
    result = client.post("/api/v1/memory/rebuild", json={"history": False}).json()
    assert result["indexed_or_queued"] == 1 and result["vector_status"] == "disabled"
    hits = client.post(
        "/api/v1/memory/search", json={"query": "introductory programming", "layer": "semantic"}
    ).json()["selected"]
    assert hits[0]["layer"] == "semantic" and hits[0]["evidence"]


@pytest.mark.skipif(
    os.getenv("TEST_LOCAL_VECTORS") != "1",
    reason="Opt-in integration requires locally cached encoder weights",
)
def test_real_chroma_persistence_search_and_deletion(cfg):
    cfg.vector_enabled = True
    with TestClient(create_app(cfg)) as c:
        cid = c.post("/api/v1/conversations", json={}).json()["id"]
        insert(c, cid, "I am studying mechanical engineering.")
        insert(c, cid, "I struggled with rotational dynamics yesterday.")
        index = c.app.state.vectors
        index.drain(c.app.state.db)
        assert index.state == "ready"
        assert index.collections["semantic"].count() >= 1 and index.collections["episodic"].count() == 1
        mid = c.get("/api/v1/memory/semantic").json()[0]["id"]
        assert mid in index.search("mechanics and rotational dynamics")
    with TestClient(create_app(cfg)) as c:
        idx = c.app.state.vectors
        idx.drain(c.app.state.db)
        assert idx.state == "ready" and mid in idx.search("mechanics")
        assert c.delete("/api/v1/memory/semantic/" + mid).status_code == 204
        assert not idx.collections["semantic"].get(ids=[mid])["ids"]
        assert c.delete("/api/v1/conversations/" + cid).status_code == 204
        assert idx.collections["semantic"].count() == 0 and idx.collections["episodic"].count() == 0
