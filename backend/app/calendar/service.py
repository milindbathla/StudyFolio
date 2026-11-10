import csv
import io
import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from icalendar import Calendar
from icalendar import Event as IcsEvent
from pydantic import ValidationError
from sqlalchemy import select

from ..contracts import EventInput, Review
from ..db import row, settings
from ..memory.extraction import normal, words
from ..models import Candidate, Conversation, Event, EventRevision, Message, now
from .dates import COMMAND, UPDATE, classify, fields, normalized, title_for


def view(s, item):
    data = row(item)
    m = s.get(Message, item.source_id) if item.source_id else None
    data["source_conversation_id"] = m.conversation_id if m else None
    if m and m.details.get("document_id"):
        data.update(
            source_document_id=m.details["document_id"], source_location=m.details.get("locator")
        )
    if isinstance(item, Event):
        data["history"] = [
            row(r)
            for r in s.scalars(
                select(EventRevision)
                .where(EventRevision.event_id == item.id)
                .order_by(EventRevision.created_at)
            )
        ]
    return data


def revision(s, event, operation, source=None):
    s.flush()
    snapshot = {
        key: str(getattr(event, key) or "")
        for key in (
            "title",
            "category",
            "description",
            "local_date",
            "start_utc",
            "end_utc",
            "timezone",
            "status",
        )
    }
    s.add(EventRevision(event_id=event.id, source_id=source, operation=operation, snapshot=snapshot))


def identity_terms(title):
    return words(title) - set(
        "the my our a an this that it new actually assignment deadline project exam examination quiz submission registration meeting date end semester is to been has extended moved postponed".split()
    )


def matching(rows, title, category):
    terms = identity_terms(title)
    result = [
        x
        for x in rows
        if x.category == category or category == "milestone" and "deadline" in title.lower()
    ]
    if terms:
        result = [x for x in result if terms <= identity_terms(x.title)]
    return result


def same_event(s, values, skip=None):
    events = s.scalars(
        select(Event).where(
            Event.status == "confirmed",
            Event.category == values["category"],
            Event.local_date == values["local_date"],
        )
    )
    return next(
        (
            e
            for e in events
            if e.id != skip
            and normal(e.title) == normal(values["title"])
            and e.start_utc == values["start_utc"]
        ),
        None,
    )


def create(s, payload, source_type="manual"):
    values = fields(payload, settings(s)["timezone"])
    duplicate = same_event(s, values)
    if duplicate:
        return duplicate
    event = Event(**values, source_type=source_type)
    s.add(event)
    revision(s, event, "create")
    return event


def edit(s, event, payload):
    values = fields(payload, event.timezone)
    if same_event(s, values, event.id):
        raise HTTPException(409, "Another confirmed event already has this title and time")
    for key, value in values.items():
        setattr(event, key, value)
    event.sequence += 1
    revision(s, event, "edit")
    return event


def confirm(s, candidate, review: Review, auto=False):
    if candidate.status == "confirmed" and candidate.event_id:
        return s.get(Event, candidate.event_id)
    if candidate.status != "proposed":
        raise HTTPException(409, "This suggestion is no longer pending")
    if candidate.needs_review and not review.event:
        raise HTTPException(422, "Review the date and submit the corrected event details")
    payload = review.event
    if not payload:
        local = (
            candidate.start_utc.astimezone(ZoneInfo(candidate.timezone)) if candidate.start_utc else None
        )
        payload = EventInput(
            title=candidate.title,
            category=candidate.category,
            date=candidate.local_date,
            time=local.time() if local else None,
            end_time=candidate.end_utc.astimezone(ZoneInfo(candidate.timezone)).time()
            if candidate.end_utc
            else None,
            timezone=candidate.timezone,
            description=candidate.description,
        )
    target_id = review.target_id or candidate.target_id
    targets = candidate.parsed.get("possible_targets", [])
    if targets and not target_id:
        raise HTTPException(422, "Choose which existing event to update")
    if review.target_id and review.target_id not in [*targets, candidate.target_id]:
        raise HTTPException(422, "Choose one of the matching calendar events")
    values = fields(payload, candidate.timezone)
    event = s.get(Event, target_id) if target_id else same_event(s, values)
    if target_id and (not event or event.status != "confirmed"):
        raise HTTPException(409, "The target is no longer confirmed")
    if event and target_id:
        if (
            candidate.parsed.get("target_sequence") is not None
            and event.sequence != candidate.parsed["target_sequence"]
        ):
            raise HTTPException(
                409,
                "The event changed after this suggestion. Reject this suggestion and edit the current event.",
            )
        if same_event(s, values, event.id):
            raise HTTPException(409, "The change would duplicate another confirmed event")
        for key, val in values.items():
            setattr(event, key, val)
        event.sequence += 1
        op = "reschedule"
    elif event:
        op = "additional source"
    else:
        event = Event(
            **values,
            source_type="conversation",
            source_id=candidate.source_id,
            synthetic=candidate.synthetic,
        )
        s.add(event)
        op = "confirm"
    event.reason, event.original_date_text, event.parsed, event.confidence = (
        candidate.reason,
        candidate.original_date_text,
        candidate.parsed,
        candidate.confidence,
    )
    event.user_confirmed = not auto
    revision(s, event, op, candidate.source_id)
    candidate.event_id = event.id
    event_id = event.id
    candidate.status = "confirmed"
    prior_ids = set(candidate.parsed.get("prior_candidates", []))
    for old in s.scalars(select(Candidate).where(Candidate.status.in_(["superseded", "duplicate"]))):
        if old.id in prior_ids or old.parsed.get("duplicate_of") in (prior_ids | {candidate.id}):
            old.event_id = event_id
            s.add(
                EventRevision(
                    event_id=event_id,
                    source_id=old.source_id,
                    operation="additional source" if old.status == "duplicate" else "prior proposal",
                    snapshot={"title": old.title, "local_date": old.local_date},
                )
            )
    return event


def extract(s, m, hints=()):
    cfg = settings(s)
    clauses = re.split(
        r"[;\n]|\band\s+(?=(?:my |our |the )?\w+\s+(?:exam|assignment|quiz))", m.content, flags=re.I
    )
    for i, clause in enumerate(clauses[:8]):
        zone = m.details.get("timezone") or cfg["timezone"]
        if (
            clause.rstrip().endswith("?")
            or re.search(r"\b(?:learned|was born|graduated)\b", clause, re.I)
            and not UPDATE.search(clause)
        ):
            continue
        hint = next(
            (
                h
                for h in hints
                if h.message_id == m.id
                and h.date_phrase in clause
                and h.title.casefold() in clause.casefold()
            ),
            None,
        )
        category = classify(clause) or (hint.category if hint else None)
        update = bool(UPDATE.search(clause))
        if not category and update and re.search(r"\b(?:it|that|deadline)\b", clause, re.I):
            category = "milestone"
        parsed = normalized(clause, m.created_at, zone) if category else None
        if not parsed:
            continue
        if (
            not update
            and not COMMAND.search(clause.strip())
            and re.search(r"\b(?:was|had|took|attended)\b", clause, re.I)
            and parsed["date"]
            and parsed["date"] < parsed["base_date"]
        ):
            continue
        key = f"{m.id}:{i}"
        if s.scalar(select(Candidate.id).where(Candidate.source_key == key)):
            continue
        title = hint.title if hint else title_for(clause, category)
        events = list(s.scalars(select(Event).where(Event.status == "confirmed")))
        pending = list(s.scalars(select(Candidate).where(Candidate.status == "proposed")))
        targets = matching(events, title, category) if update else []
        priors = matching(pending, title, category) if update else []
        if parsed["prior"]:
            old = normalized(parsed["prior"], m.created_at, zone)
            if old and old["date"]:
                targets = [t for t in targets if t.local_date == old["date"]]
                priors = [t for t in priors if t.local_date == old["date"]]
        # Pending suggestions about a confirmed event refer to the same underlying deadline.
        priors = [p for p in priors if not p.target_id or not any(t.id == p.target_id for t in targets)]
        count = len(targets) + len(priors)
        ref = (targets or priors)[0] if update and count == 1 else None
        if ref:
            title, category = ref.title, ref.category
            if ref.start_utc and not parsed["time"]:
                zone = ref.timezone
                parsed["time"] = ref.start_utc.astimezone(ZoneInfo(zone)).strftime("%H:%M")
                parsed["time_inherited"] = True
        elif update and count != 1:
            parsed["review"] = (
                "Choose the affected deadline"
                if count
                else "No unique earlier deadline was found. Review before adding."
            )
        if len(targets) > 1 or (targets and priors):
            parsed["possible_targets"] = [x.id for x in targets]
        if len(priors) > 1:
            parsed["ambiguous_proposals"] = [x.id for x in priors]
            parsed["review"] = (
                "Several pending suggestions match. Resolve the earlier suggestions before adding this date."
            )
        base = dict(
            title=title,
            category=category,
            timezone=zone,
            local_date=parsed["date"],
            all_day=not parsed["time"],
            start_utc=None,
        )
        if parsed["date"]:
            try:
                base = fields(
                    EventInput(title=title, category=category, date=parsed["date"], time=parsed["time"]),
                    zone,
                )
            except (ValueError, ValidationError):
                parsed["review"] = "Choose a valid local date and time"
        if ref:
            base["description"] = ref.description
            if ref.start_utc and ref.end_utc and base["start_utc"]:
                base["end_utc"] = base["start_utc"] + (ref.end_utc - ref.start_utc)
        same = next(
            (
                p
                for p in pending
                if not update
                and p.local_date == base["local_date"]
                and p.start_utc == base["start_utc"]
                and normal(p.title) == normal(title)
            ),
            None,
        )
        if same:
            parsed["duplicate_of"] = same.id
        target = targets[0] if count == 1 and targets else None
        if target:
            parsed["target_sequence"] = target.sequence
        if priors and count == 1:
            prior = priors[0]
            parsed["prior_candidates"] = [*prior.parsed.get("prior_candidates", []), prior.id]
            prior.status = "superseded"
            if prior.target_id:
                target = s.get(Event, prior.target_id)
                parsed["target_sequence"] = target.sequence if target else None
        candidate = Candidate(
            **base,
            source_key=key,
            source_id=m.id,
            status="duplicate" if same else "proposed",
            original_date_text=parsed["original"],
            parsed=parsed,
            target_id=target.id if target else None,
            needs_review=bool(parsed["review"]),
            reason=f"Academic {category} mentioned with a date",
            confidence=0.68 if parsed["review"] else 0.94,
            synthetic=s.get(Conversation, m.conversation_id).synthetic,
        )
        s.add(candidate)
        s.flush()
        if same:
            continue
        duplicate = same_event(s, base) if not update and base["local_date"] else None
        if (
            duplicate
            or not candidate.needs_review
            and (
                not cfg["require_confirmation"]
                or cfg["auto_explicit"]
                and COMMAND.search(clause.strip())
            )
        ):
            if not m.details.get("document_id"):
                confirm(s, candidate, Review(), auto=True)


def events_in_window(
    s, start=None, end=None, category=None, query="", upcoming=False, overdue=False, at=None
):
    current = at or now()
    tz = ZoneInfo(settings(s)["timezone"])
    today = current.astimezone(tz).date()
    results = []
    for e in s.scalars(
        select(Event)
        .where(Event.status == "confirmed")
        .order_by(Event.local_date, Event.start_utc, Event.title)
    ):
        local_day = (
            e.start_utc.astimezone(tz).date() if e.start_utc else date.fromisoformat(e.local_date)
        )
        past = e.start_utc < current if e.start_utc else local_day < today
        if (
            (start and local_day < start)
            or (end and local_day > end)
            or (category and e.category != category)
            or query.casefold() not in (e.title + " " + e.description).casefold()
            or (upcoming and past)
            or (overdue and not past)
        ):
            continue
        results.append(e)
    return sorted(
        results,
        key=lambda e: (
            e.start_utc.astimezone(tz).date().isoformat() if e.start_utc else e.local_date,
            e.start_utc or datetime.min.replace(tzinfo=UTC),
        ),
    )


def ics(s):
    cal = Calendar()
    cal.add("prodid", "-//Studyfolio//Local Academic Calendar//EN")
    cal.add("version", "2.0")
    for e in events_in_window(s):
        item = IcsEvent()
        item.add("uid", e.id + "@studyfolio.local")
        item.add("dtstamp", e.updated_at.astimezone(UTC))
        item.add("sequence", e.sequence)
        item.add("summary", e.title)
        item.add("description", e.description)
        item.add("categories", e.category)
        item.add("dtstart", date.fromisoformat(e.local_date) if e.all_day else e.start_utc)
        if e.all_day or e.end_utc:
            item.add(
                "dtend", date.fromisoformat(e.local_date) + timedelta(days=1) if e.all_day else e.end_utc
            )
        cal.add_component(item)
    return cal.to_ical()


def import_csv(s, content):
    reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), strict=True)
    if not {"title", "date"} <= set(reader.fieldnames or []):
        raise HTTPException(422, "CSV requires title and date columns")
    accepted, errors = [], []
    try:
        for line, r in enumerate(reader, 2):
            try:
                payload = EventInput(
                    title=r.get("title"),
                    date=r.get("date"),
                    description=r.get("description") or "",
                    category=r.get("category") or "assignment",
                    time=r.get("time") or None,
                )
                accepted.append(create(s, payload, "csv").id)
            except (ValueError, ValidationError) as exc:
                errors.append(
                    {
                        "line": line,
                        "error": exc.errors()[0]["msg"]
                        if isinstance(exc, ValidationError)
                        else str(exc),
                    }
                )
    except csv.Error as exc:
        errors.append({"line": reader.line_num, "error": str(exc)})
    return {"accepted": accepted, "errors": errors}
