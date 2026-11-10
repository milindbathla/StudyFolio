"""Optional real LiteLLM transport verification using a local deterministic HTTP endpoint."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.mark.skipif(os.getenv("TEST_LOCAL_LITELLM") != "1", reason="Opt-in integration requires LiteLLM")
def test_real_litellm_chat_extraction_and_reflection_on_loopback(cfg, monkeypatch):
    operations = []

    class Endpoint(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            system, source = body["messages"]
            payload = json.loads(source["content"])
            if system["content"].startswith("Extract durable"):
                op = "extract"
                fact = dict(
                    path="learning_preferences.preferred_examples",
                    value="concept maps",
                    message_id=payload["id"],
                    quote=payload["content"],
                    origin="inferred",
                    confidence=0.71,
                )
                answer = json.dumps({"facts": [fact], "episodes": [], "dates": []})
            elif system["content"].startswith("Propose minimal"):
                op = "reflect"
                m = payload["messages"][0]
                patch = dict(
                    operation="ADD",
                    path="behavioral_patterns.common_requests",
                    value="concept maps",
                    message_id=m["id"],
                    quote=m["content"],
                    origin="inferred",
                    confidence=0.72,
                )
                answer = json.dumps({"patches": [patch]})
            else:
                op = "chat"
                answer = "Fixture reply from the local HTTP endpoint."
            operations.append(op)
            result = json.dumps(
                {
                    "id": "fixture",
                    "object": "chat.completion",
                    "created": 1700000000,
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": answer},
                        }
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.end_headers()
            self.wfile.write(result)

    with ThreadingHTTPServer(("127.0.0.1", 0), Endpoint) as http:
        loop = threading.Thread(target=http.serve_forever, daemon=True)
        loop.start()
        try:
            base = f"http://127.0.0.1:{http.server_port}/v1"
            monkeypatch.setenv("OPENAI_API_BASE", base)
            monkeypatch.setenv("OPENAI_BASE_URL", base)
            monkeypatch.setenv("OPENAI_API_KEY", "local-fixture-only")
            monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
            monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
            cfg.llm_enabled, cfg.llm_model = True, "openai/studyfolio-loopback-fixture"
            with TestClient(create_app(cfg)) as api:
                cid = api.post("/api/v1/conversations", json={}).json()["id"]
                turn = api.post(
                    "/api/v1/chat", json={"content": "I asked for concept maps.", "conversation_id": cid}
                ).json()
                assert (
                    turn["assistant"]["details"]["mode"] == "model"
                    and "Fixture reply" in turn["assistant"]["content"]
                )
                api.post(f"/api/v1/conversations/{cid}/reflect")
                while api.app.state.memory.run_one():
                    pass
                assert operations == ["chat", "extract", "reflect"]
                assertions = api.get("/api/v1/persona").json()["assertions"]
                assert {a["path"] for a in assertions} == {
                    "learning_preferences.preferred_examples",
                    "behavioral_patterns.common_requests",
                }
                assert all(
                    a["status"] == "pending" and a["evidence"][0]["message_id"] == turn["user"]["id"]
                    for a in assertions
                )
        finally:
            http.shutdown()
            loop.join()
