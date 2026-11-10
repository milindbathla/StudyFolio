"""Exercise a disposable Neo4j Community distribution and real driver with synthetic evidence only."""

import argparse
import os
import secrets
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from app.config import Config
from app.main import create_app
from app.sources import parse_job
from fastapi.testclient import TestClient
from neo4j import GraphDatabase


def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("java", type=Path)
    parser.add_argument("distribution", type=Path)
    parser.add_argument("--vectors", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="studyfolio-bolt-") as temporary:
        root = Path(temporary)
        conf = root / "conf"
        conf.mkdir()
        bolt = port()
        (conf / "neo4j.conf").write_text(
            f"server.default_listen_address=127.0.0.1\nserver.bolt.listen_address=127.0.0.1:{bolt}\nserver.http.enabled=false\nserver.https.enabled=false\nserver.memory.pagecache.size=64M\n"
        )
        uri = f"bolt://127.0.0.1:{bolt}"
        with (root / "console.log").open("w") as log:
            proc = subprocess.Popen(
                [
                    str(args.java),
                    "-Xms128m",
                    "-Xmx384m",
                    "--add-opens=java.base/java.nio=ALL-UNNAMED",
                    "--add-opens=java.base/java.io=ALL-UNNAMED",
                    "-cp",
                    str(args.distribution / "lib" / "*"),
                    "org.neo4j.server.CommunityEntryPoint",
                    "--home-dir=" + str(root),
                    "--config-dir=" + str(conf),
                ],
                stdout=log,
                stderr=log,
                cwd=root,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                for _ in range(120):
                    if proc.poll() is not None:
                        raise RuntimeError((root / "console.log").read_text()[-1800:])
                    try:
                        with socket.create_connection(("127.0.0.1", bolt), 0.3):
                            break
                    except OSError:
                        time.sleep(0.5)
                password = secrets.token_urlsafe(24)
                with (
                    GraphDatabase.driver(uri, auth=("neo4j", "neo4j")) as driver,
                    driver.session(database="system") as session,
                ):
                    session.run(
                        "ALTER CURRENT USER SET PASSWORD FROM $old TO $new",
                        old="neo4j",
                        new=password,
                    ).consume()
                os.environ.update(
                    NEO4J_URI=uri, NEO4J_USER="neo4j", NEO4J_PASSWORD=password
                )
                cfg = Config(
                    db_url="sqlite:///" + (root / "sources.db").as_posix(),
                    chroma_dir=root / "chroma",
                    vector_enabled=args.vectors,
                    worker=False,
                    llm_enabled=False,
                )
                with TestClient(create_app(cfg)) as client:
                    doc = client.post(
                        "/api/v1/sources/upload",
                        files={
                            "file": ("sample.json", b'{"institution":"IIT Kanpur"}')
                        },
                    ).json()
                    eng = client.app.state.memory
                    parse_job(eng, doc["id"])
                    client.post(
                        "/api/v1/sources/" + doc["id"] + "/confirm",
                        json={
                            "version": 1,
                            "fields": [
                                {"pointer": "/institution", "value": "IIT Kanpur"}
                            ],
                        },
                    ).raise_for_status()
                    import pymupdf

                    with pymupdf.open() as pdf:
                        page = pdf.new_page()
                        page.insert_text((35, 40), "Academic Transcript")
                        page.insert_text((35, 65), "Institution: IIT Kanpur")
                        other = client.post(
                            "/api/v1/sources/upload",
                            files={"file": ("synthetic-transcript.pdf", pdf.tobytes())},
                        ).json()
                    parse_job(eng, other["id"])
                    if args.vectors:
                        eng.vectors.drain(eng.db, limit=200)
                    eng.graph.sync(eng.db)
                    trace = client.post(
                        "/api/v1/retrieval/debug",
                        json={"query": "In which college I study?"},
                    ).json()
                    assert (
                        trace["graph_status"] == "Neo4j connected"
                        and trace["graph"]
                        and trace["answer"] == "You study at IIT Kanpur."
                    ), trace
                    second = client.post(
                        "/api/v1/retrieval/debug",
                        json={"query": "In which institution do I study?"},
                    ).json()
                    assert second["answer"] == trace["answer"] and set(
                        second["direct"]
                    ) == set(trace["direct"])
                    assert {
                        e["document_id"] for e in trace["selected"][0]["evidence"]
                    } == {doc["id"], other["id"]}
                    if args.vectors:
                        assert trace["semantic"] and trace["expansion"], trace
                    import json

                    print(
                        json.dumps(
                            {
                                k: trace[k]
                                for k in (
                                    "query",
                                    "normalized_query",
                                    "intent",
                                    "direct",
                                    "semantic",
                                    "graph",
                                    "expansion",
                                    "rrf",
                                    "answer",
                                    "graph_status",
                                    "vector_status",
                                )
                            }
                        )
                    )
                    client.delete("/api/v1/sources/" + doc["id"]).raise_for_status()
                    client.delete("/api/v1/sources/" + other["id"]).raise_for_status()
                    eng.graph.sync(eng.db)
                    with eng.graph.driver.session() as session:
                        assert (
                            session.run(
                                "MATCH (:SFEntity {owner:$owner})-[e:SF_REL]->() RETURN count(e) AS n",
                                owner=eng.graph.owner,
                            ).single()["n"]
                            == 0
                        )
            finally:
                proc.terminate()
                proc.wait(timeout=25)


if __name__ == "__main__":
    main()
