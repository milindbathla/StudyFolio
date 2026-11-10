from fastapi.testclient import TestClient

from app.cli import seed
from app.main import create_app


def test_demo_is_repeatable_and_synthetic(cfg):
    seed(cfg)
    seed(cfg)
    with TestClient(create_app(cfg)) as c:
        threads = c.get("/api/v1/conversations").json()
        assert len(threads) == 6 and all(t["synthetic"] for t in threads)
        events = c.get("/api/v1/calendar/events").json()
        assert len(events) == 1 and events[0]["local_date"] == "2026-11-20"
        assert events[0]["synthetic"] and len(events[0]["history"]) == 2
        assert all(m["synthetic"] for m in c.get("/api/v1/memory/semantic").json())
        assert (
            c.get("/api/v1/persona").json()["profile"]["learning_preferences"]["explanation_depth"]
            == "detailed explanations with mathematical derivations"
        )
