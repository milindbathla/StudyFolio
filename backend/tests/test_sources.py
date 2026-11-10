import json
import os

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.cdf import fusion
from app.main import create_app
from app.provider import StubProvider
from app.source_parse import parse_pdf
from app.sources import parse_job

P = "/api/v1"


def pdf(*pages):
    with pymupdf.open() as doc:
        for lines in pages:
            page = doc.new_page()
            for i, line in enumerate(lines):
                page.insert_text((42, 42 + i * 18), line)
        return doc.tobytes()


def upload(c, raw, name="source.pdf", kind="auto"):
    res = c.post(P + "/sources/upload", files={"file": (name, raw)}, data={"kind": kind})
    assert res.status_code == 202, res.text
    did = res.json()["id"]
    parse_job(c.app.state.memory, did)
    d = c.get(P + "/sources/" + did).json()
    assert d["status"] == "ready", d
    return d


TRANS = pdf(
    [
        "Academic Transcript",
        "Institution: Indian Institute of Technology Kanpur",
        "Programme: B.Tech",
        "Department: Mechanical Engineering",
        "CPI: 8.5",
        "Academic session: 2025-26",
        "Semester 1",
        "SPI: 8.7",
        "MTH112M Calculus A 6",
    ],
    ["Semester 2", "ME209 Rotational Dynamics 8 B", "Current Course(s)", "NO DATA FOUND"],
)
CURR = pdf(
    [
        "Curriculum template",
        "BT",
        "Semester 3",
        "ME209 Mechanics 8 credits",
        "ME623 prerequisite: MTH112M",
    ],
    ["BTH", "Semester 3", "ME999 Research 6 credits"],
)
SURVEY = json.dumps(
    {
        "goal_ds_ai": True,
        "goal_quant": False,
        "skill_ml_level": "Beginner",
        "data_provenance": {"synthetic": ["goal_ds_ai", "skill_ml_level"]},
    }
).encode()


def trace(c, q):
    res = c.post(P + "/retrieval/debug", json={"query": q})
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.parametrize("model", [False, True])
def test_institution_aliases_chat(cfg, model):
    with TestClient(create_app(cfg, StubProvider() if model else None)) as c:
        d = upload(c, TRANS)
        cid = c.post(P + "/conversations", json={}).json()["id"]
        for query in [
            "In which college I study?",
            "In which institution do I study?",
            "Which university do I attend?",
            "Where am I pursuing my B.Tech?",
            "What is my institute?",
            "Where am I enrolled?",
        ]:
            a = c.post(P + "/chat", json={"conversation_id": cid, "content": query}).json()["assistant"]
            assert a["content"] == "You study at IIT Kanpur."
            evidence = a["details"]["sources"][0]["evidence"][0]
            assert evidence["document_id"] == d["id"] and evidence["location"].startswith("page 1")


def test_survey_review_and_revisions(client):
    d = upload(client, SURVEY, "anonymous.json")
    assert all(i["status"] == "review" and "synthetic" in i["provenance"] for i in d["items"])
    assert not trace(client, "What are my goals?")["selected"]
    res = client.post(
        P + "/sources/" + d["id"] + "/confirm",
        json={
            "version": d["version"],
            "fields": [
                {"pointer": "/goal_ds_ai", "value": True},
                {"pointer": "/goal_quant", "value": False},
                {"pointer": "/skill_ml_level", "value": "Beginner"},
                {"pointer": "/institution", "value": "Example College"},
            ],
        },
    )
    assert res.status_code == 200, res.text
    assert "ds ai" in trace(client, "What are my goals?")["answer"]
    assert "self-assessment" in trace(client, "Am I good at machine learning?")["answer"]
    assert upload(client, SURVEY, "renamed.json")["id"] == d["id"]
    assert client.get(P + "/sources/" + d["id"] + "/original").content == SURVEY
    assert client.post(P + "/sources/upload", files={"file": ("x.json", b"{")}).status_code == 422
    assert (
        client.post(
            P + "/sources/" + d["id"] + "/confirm",
            json={"version": 1, "fields": [{"pointer": "/institution", "value": "stale"}]},
        ).status_code
        == 409
    )


def test_academic_template_restart_and_delete(cfg):
    with TestClient(create_app(cfg)) as c:
        d = upload(c, TRANS)
        tpl = upload(c, CURR, kind="curriculum_template")
        assert trace(c, "What is my current CPI?")["answer"] == "Your documented CPI is 8.5."
        assert trace(c, "What grade did I get in MTH 112M?")["selected"][0]["value"] == "A"
        assert not trace(c, "What grade did I get in MTH112?")["selected"]
        assert (
            "verified current-course" in trace(c, "Which courses am I taking this semester?")["answer"]
        )
        assert {r["value"] for r in trace(c, "Which courses have I completed?")["selected"]} == {
            "ME209",
            "MTH112M",
        }
        assert {r["value"] for r in trace(c, "BT template semester 3 courses")["selected"]} == {"ME209"}
        assert {r["value"] for r in trace(c, "BTH template semester 3 courses")["selected"]} == {"ME999"}
        assert trace(c, "Prerequisites of ME623?")["selected"][0]["value"] == "MTH112M"
        assert trace(c, "Where do I study?")["graph"]
        assert c.get(P + "/calendar/candidates").json() == []
    with TestClient(create_app(cfg)) as c:
        assert trace(c, "Which college?")["selected"]
        a = c.get(P + "/persona").json()["assertions"]
        ident = next(i for i in a if i["path"] == "identity.institution")
        c.patch(
            P + "/persona",
            json={
                "operation": "REPLACE",
                "path": ident["path"],
                "target_id": ident["id"],
                "value": "New College",
            },
        )
        assert trace(c, "Where do I study?")["answer"] == "You study at New College."
        assert c.delete(P + "/sources/" + d["id"]).status_code == 204
        assert not trace(c, "What is my CPI?")["selected"]
        assert c.get(P + "/sources/" + tpl["id"]).status_code == 200


def test_independent_support_and_questions(client, cid):
    one = upload(client, TRANS)
    two = upload(
        client,
        pdf(
            [
                "Academic Transcript",
                "Institution: Indian Institute of Technology Kanpur",
                "Department: Mechanics",
            ]
        ),
    )
    client.delete(P + "/sources/" + one["id"])
    r = trace(client, "Which college?")
    assert r["selected"][0]["evidence"][0]["document_id"] == two["id"]
    client.delete(P + "/sources/" + two["id"])
    for q in ["Which college?", "What is my institution?"]:
        a = client.post(P + "/chat", json={"conversation_id": cid, "content": q}).json()["assistant"]
        assert not a["details"]["sources"]


def test_notice_unreadable_and_rrf(client):
    upload(client, pdf(["Academic notice", "My physics quiz is on November 19, 2030."]))
    assert len(client.get(P + "/calendar/candidates").json()) == 1
    raw = pdf([])
    kind, pages, rows, warnings = parse_pdf(raw, "auto")
    assert warnings and not rows
    assert fusion([["b", "a"], ["a", "b"], ["a"]])[0][0] == "a"


def test_template_edges_do_not_imply_enrollment_and_conflicts_abstain(client):
    upload(client, TRANS)
    upload(client, CURR)
    r = trace(client, "Which completed mathematics courses are prerequisites in my curriculum?")
    assert "MTH112M is a documented prerequisite of ME623" in r["answer"]
    other = upload(client, pdf(["Academic Transcript", "Institution: Second College"]))
    assert "disagree" in trace(client, "Which university do I attend?")["answer"]
    assert other["conflicts"]


def test_source_cannot_be_accessed_by_another_sql_user(client):
    from app.models import User
    from app.source_models import Document

    d = upload(client, TRANS)
    with client.app.state.db.write() as s:
        alien = User(name="Synthetic other user")
        s.add(alien)
        s.flush()
        s.get(Document, d["id"]).user_id = alien.id
    assert client.get(P + "/sources/" + d["id"]).status_code == 404
    assert client.get(P + "/sources/" + d["id"] + "/original").status_code == 404
    assert not trace(client, "In which college do I study?")["selected"]


@pytest.mark.skipif(
    os.getenv("TEST_LOCAL_VECTORS") != "1", reason="Requires cached local sentence encoder"
)
def test_real_document_vectors_expansion_and_repair(cfg):
    cfg.vector_enabled = True
    with TestClient(create_app(cfg)) as c:
        doc = upload(c, TRANS)
        upload(c, CURR)
        engine = c.app.state.memory
        engine.vectors.drain(engine.db, limit=256)
        r = trace(c, "What courses have I completed?")
        assert r["semantic"] and r["graph"] and r["expansion"] and r["rrf"]
        assert engine.vectors.collections["document_chunks"].count() > 0
        ids = [v["id"] for v in doc["items"] if v["status"] == "active"]
        assert set(engine.vectors.collections["document_chunks"].get(ids=ids)["ids"]) == set(ids)
    with TestClient(create_app(cfg)) as c:
        c.app.state.vectors.drain(c.app.state.db)
        assert trace(c, "What are my completed courses?")["semantic"]
        c.delete(P + "/sources/" + doc["id"]).raise_for_status()
        assert not c.app.state.vectors.collections["document_chunks"].get(ids=ids)["ids"]


def test_printed_grade_credit_rows_and_programme_variants(client):
    transcript = upload(client, TRANS)
    rows = {i["value"]["raw"]: i for i in transcript["items"] if i["relation"] == "HAS_COMPLETED_COURSE"}
    assert (
        rows["MTH112M"]["value"]["grade"],
        rows["MTH112M"]["value"]["credits"],
        rows["MTH112M"]["value"]["page"],
    ) == ("A", 6, 1)
    assert (
        rows["ME209"]["value"]["grade"],
        rows["ME209"]["value"]["credits"],
        rows["ME209"]["value"]["page"],
    ) == ("B", 8, 2)
    headings = ["BT", "B.Tech Honours", "BTM", "Dual-degree", "Double-major", "Minor"]
    fixture = pdf(
        *[
            ["Curriculum template", heading, "Semester 4", f"ME{330 + i} Engineering 6 credits"]
            for i, heading in enumerate(headings)
        ]
    )
    d = upload(client, fixture)
    for i, heading in enumerate(headings):
        records = trace(client, f"Which courses are in the {heading} template semester 4?")["selected"]
        assert [r["value"] for r in records] == [f"ME{330 + i}"]
        assert records[0]["evidence"][0]["location"].startswith(f"page {i + 1},")
    assert len(client.get(P + "/curriculum/programmes").json()) == 6
    assert len(d["pages"]) == 6


def test_invalid_pdf_state_and_retry(client):
    result = client.post(
        P + "/sources/upload", files={"file": ("incomplete.pdf", b"%PDF-broken")}
    ).json()
    parse_job(client.app.state.memory, result["id"])
    doc = client.get(P + "/sources/" + result["id"]).json()
    assert doc["status"] == "failed" and doc["warnings"] and not doc["items"]
    assert (
        client.post(P + "/sources/" + doc["id"] + "/reprocess", json={"kind": "auto"}).json()["status"]
        == "queued"
    )


def test_ruled_curriculum_columns_keep_their_semesters():
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((40, 30), "Curriculum template")
        page.insert_text((40, 50), "BTM")
        for x in [40, 220, 400]:
            page.draw_line((x, 75), (x, 135))
        for y in [75, 105, 135]:
            page.draw_line((40, y), (400, y))
        for x, t, h in [
            (46, "ME431 Design 6 credits", "Semester 3"),
            (226, "ME511 Project 8 credits", "Semester 4"),
        ]:
            page.insert_text((x, 94), h)
            page.insert_text((x, 124), t)
        _, _, rows, _ = parse_pdf(doc.tobytes(), "curriculum_template")
    assert {
        (r.value["raw"], r.value["semester"], r.value["programme"])
        for r in rows
        if r.relation == "HAS_CURRICULUM_COURSE"
    } == {("ME431", "3", "BTM"), ("ME511", "4", "BTM")}
