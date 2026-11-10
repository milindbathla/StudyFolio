from datetime import UTC, datetime

import pytest
from conftest import FIXED, insert
from icalendar import Calendar

from app.calendar.dates import classify, normalized

P = "/api/v1"


@pytest.mark.parametrize(
    ("phrase", "day"),
    [
        ("18 November 2026 at 9 AM", "2026-11-18"),
        ("November 18", "2026-11-18"),
        ("next Friday at midnight", "2026-11-13"),
        ("tomorrow", "2026-11-11"),
        ("in 3 days", "2026-11-13"),
        ("day after tomorrow", "2026-11-12"),
        ("2026-12-02", "2026-12-02"),
    ],
)
def test_date_resolution(phrase, day):
    assert normalized(phrase, FIXED, "Asia/Kolkata")["date"] == day


def test_ambiguity_and_source_timezone():
    assert normalized("quiz at midnight next Friday", FIXED, "Asia/Kolkata")["review"]
    assert normalized("exam on 03/04", FIXED, "Asia/Kolkata")["date"] is None
    assert normalized("meeting next week", FIXED, "Asia/Kolkata")["review"]
    moment = datetime(2026, 11, 10, 20, tzinfo=UTC)
    assert normalized("tomorrow", moment, "Asia/Kolkata")["date"] == "2026-11-12"
    assert normalized("tomorrow", moment, "America/Chicago")["date"] == "2026-11-11"


def test_classification_and_historical_mentions(client, cid):
    assert classify("I learned Python in 2024.") is None
    for text in [
        "I learned Python in 2024.",
        "My exam was on November 2, 2026.",
        "Which exams do I have on November 18?",
    ]:
        insert(client, cid, text)
    assert client.get(P + "/calendar/candidates").json() == []


def test_passive_timed_and_ical(client, cid):
    mid = insert(client, cid, "My ME209 end-semester exam is on 18 November 2026 at 9 AM.")
    assert client.get(P + "/calendar/events").json() == []
    c = client.get(P + "/calendar/candidates").json()[0]
    assert c["title"] == "ME209 End-Semester Examination"
    event = client.post(f"{P}/calendar/candidates/{c['id']}/confirm").json()
    assert (
        datetime.fromisoformat(event["start_utc"]) == datetime(2026, 11, 18, 3, 30, tzinfo=UTC)
        and event["source_id"] == mid
    )
    assert client.post(f"{P}/calendar/candidates/{c['id']}/confirm").json()["id"] == event["id"]
    raw = client.get(P + "/calendar/export.ics").content
    ve = Calendar.from_ical(raw).walk("VEVENT")[0]
    assert ve["DTSTART"].dt == datetime(2026, 11, 18, 3, 30, tzinfo=UTC)
    assert str(ve["UID"]) == event["id"] + "@studyfolio.local"


def test_explicit_command_and_policy(client, cid):
    insert(client, cid, "Add my physics quiz on November 19 at 10 AM.")
    assert len(client.get(P + "/calendar/events").json()) == 1
    client.patch(P + "/settings", json={"auto_explicit": False})
    insert(client, cid, "Add my chemistry quiz on November 20 at 9 AM.")
    assert len(client.get(P + "/calendar/candidates").json()) == 1


def test_correct_pending_and_confirmed(client, cid):
    first = insert(client, cid, "My mechanics assignment is due on November 18, 2026.")
    insert(client, cid, "Actually, the assignment deadline has been moved to November 20, 2026.")
    chosen = client.get(P + "/calendar/candidates").json()
    assert len(chosen) == 1 and chosen[0]["local_date"] == "2026-11-20"
    e = client.post(f"{P}/calendar/candidates/{chosen[0]['id']}/confirm").json()
    assert e["title"] == "Mechanics assignment" and any(r["source_id"] == first for r in e["history"])
    insert(client, cid, "My assignment deadline moved from November 20 to November 22.")
    c = client.get(P + "/calendar/candidates").json()[0]
    assert c["target_id"] == e["id"]
    e2 = client.post(f"{P}/calendar/candidates/{c['id']}/confirm").json()
    assert e2["id"] == e["id"] and e2["sequence"] == 1 and e2["local_date"] == "2026-11-22"
    assert len(client.get(P + "/calendar/events").json()) == 1
    client.post(f"{P}/conversations/{cid}/reprocess")
    while client.app.state.memory.run_one():
        pass
    assert len(client.get(P + "/calendar/events").json()) == 1
    assert not client.get(P + "/calendar/candidates").json()


def test_ambiguous_update_requires_selected_target(client, cid):
    a = client.post(
        P + "/calendar/events", json={"title": "Physics assignment", "date": "2026-11-18"}
    ).json()
    b = client.post(
        P + "/calendar/events", json={"title": "Math assignment", "date": "2026-11-19"}
    ).json()
    insert(client, cid, "The assignment deadline moved to November 20.")
    c = client.get(P + "/calendar/candidates").json()[0]
    assert set(c["parsed"]["possible_targets"]) == {a["id"], b["id"]}
    assert client.post(f"{P}/calendar/candidates/{c['id']}/confirm").status_code == 422
    payload = {"target_id": a["id"], "event": {"title": a["title"], "date": "2026-11-20"}}
    assert (
        client.post(f"{P}/calendar/candidates/{c['id']}/confirm", json=payload).json()["id"] == a["id"]
    )
    assert client.get(P + "/calendar/events/" + b["id"]).json()["local_date"] == "2026-11-19"


def test_unrelated_assignment_and_midnight(client, cid):
    old = client.post(
        P + "/calendar/events", json={"title": "Physics assignment", "date": "2026-11-18"}
    ).json()
    insert(client, cid, "My chemistry assignment moved to November 21.")
    insert(client, cid, "Assignment 4 is due next Friday at midnight.")
    candidates = client.get(P + "/calendar/candidates").json()
    assert len(candidates) == 2 and all(c["needs_review"] and not c["target_id"] for c in candidates)
    assert client.get(P + "/calendar/events/" + old["id"]).json()["local_date"] == "2026-11-18"
    assert (
        client.post(f"{P}/calendar/candidates/{candidates[0]['id']}/reject").json()["status"]
        == "rejected"
    )


def test_csv_validation_dedupe_escaping_and_all_day(client):
    csv = 'title,date,description,category\n"Quiz, 1",2026-11-19,"Read; revise",quiz\nWrong,not-a-date,,exam\n'
    out = client.post(P + "/calendar/import/csv", json={"content": csv}).json()
    assert len(out["accepted"]) == 1 and out["errors"][0]["line"] == 3
    client.post(P + "/calendar/import/csv", json={"content": csv})
    assert len(client.get(P + "/calendar/events").json()) == 1
    ve = Calendar.from_ical(client.get(P + "/calendar/export.ics").content).walk("VEVENT")[0]
    assert str(ve["SUMMARY"]) == "Quiz, 1" and str(ve["DTEND"].dt) == "2026-11-20"


def test_manual_dst_validation_and_local_filter(client):
    bad = {"title": "Appointment", "date": "2026-03-08", "time": "02:30", "timezone": "America/New_York"}
    assert client.post(P + "/calendar/events", json=bad).status_code == 422
    good = bad | {"date": "2026-11-12", "time": "23:00"}
    event = client.post(P + "/calendar/events", json=good).json()
    assert (
        client.get(P + "/calendar/events?start=2026-11-13&end=2026-11-13").json()[0]["id"] == event["id"]
    )
    assert (
        client.patch(
            P + "/calendar/events/" + event["id"], json={"description": "Course adviser"}
        ).json()["sequence"]
        == 1
    )
    assert client.delete(P + "/calendar/events/" + event["id"]).status_code == 204
