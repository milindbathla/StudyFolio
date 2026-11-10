import hashlib
from pathlib import PureWindowsPath

from fastapi import HTTPException
from sqlalchemy import select

from .calendar.service import extract as dates
from .contracts import EpisodeProposal, FactProposal
from .memory import episodes, facts, working
from .models import Candidate, Conversation, Event, EventRevision, Evidence, Message, Semantic, now
from .source_models import Document, SourceItem
from .source_parse import entry, mapping, parse_pdf, survey


def receive(s, filename, raw, kind):
    filename = PureWindowsPath(filename or "upload").name[:180]
    if not raw or len(raw) > 16 * 1024 * 1024:
        raise HTTPException(413, "Upload a file between 1 byte and 16 MiB")
    pdf = raw.startswith(b"%PDF-")
    if pdf and kind == "survey_json" or not pdf and kind not in ("auto", "survey_json"):
        raise HTTPException(422, "File content and selected type do not match")
    if not pdf:
        try:
            survey(raw)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise HTTPException(422, "Invalid or oversized survey JSON") from exc
        kind = "survey_json"
    digest = hashlib.sha256(raw).hexdigest()
    prior = s.scalar(select(Document).where(Document.digest == digest))
    if prior:
        return prior
    thread = Conversation(title="Source · " + filename, closed=True)
    s.add(thread)
    s.flush()
    doc = Document(
        filename=filename, raw=raw, digest=digest, kind=kind, status="queued", journal_id=thread.id
    )
    s.add(doc)
    s.flush()
    return doc


def publish(s, engine, doc, item, confirmed=False):
    c = s.get(Conversation, doc.journal_id)
    text = item.excerpt
    m = working.add_message(
        s,
        c,
        "user",
        text,
        doc.created_at if not confirmed else None,
        details={
            "document_id": doc.id,
            "filename": doc.filename,
            "locator": item.locator,
            "provenance": item.provenance,
        },
    )
    item.message_id = m.id
    path = mapping(item.field)[1]
    value = item.value["raw"]
    if item.relation == "HAS_GOAL" and isinstance(value, bool):
        value = item.field.removeprefix("goal_").replace("_", " ")
    if path and value is not None and str(value).strip() and len(str(value)) <= 600:
        v = str(value)
        p = FactProposal(
            path=path, value=v, quote=text[:600], message_id=m.id, confidence=0.97, correction=confirmed
        )
        a = facts.accept(s, p, m, engine.vectors, manual=confirmed, source_verified=True)
        if a:
            item.memory_id = a.semantic_id
    if doc.kind == "academic_notice":
        dates(s, m)


def retire(s, item):
    item.status = "superseded"
    if item.message_id:
        for candidate in s.scalars(
            select(Candidate).where(
                Candidate.source_id == item.message_id, Candidate.status == "proposed"
            )
        ):
            candidate.status = "superseded"
        for event in s.scalars(
            select(Event).where(Event.source_id == item.message_id, Event.status == "confirmed")
        ):
            independent = s.scalar(
                select(EventRevision.id).where(
                    EventRevision.event_id == event.id, EventRevision.source_id != item.message_id
                )
            )
            if not independent and event.sequence == 0:
                event.status = "cancelled"
                event.cancelled_at = now()
    if item.memory_id:
        f = s.get(Semantic, item.memory_id)
        if f and f.status in ("active", "pending"):
            other = s.scalar(
                select(Evidence.id).where(
                    Evidence.memory_id == f.id, Evidence.message_id != item.message_id
                )
            )
            if other:
                assertion = facts.assertion_for(s, f)
                for link in s.scalars(
                    select(Evidence).where(
                        Evidence.message_id == item.message_id,
                        Evidence.memory_id.in_([f.id, assertion.id]),
                    )
                ):
                    s.delete(link)
            else:
                facts.transition(s, f, "superseded", now())
                facts.transition(s, facts.assertion_for(s, f), "superseded", now())


def parse_job(engine, doc_id, ocr=False):
    db = engine.db
    with db.write() as s:
        doc = s.get(Document, doc_id)
        if not doc or doc.status != "queued":
            return
        doc.status = "processing"
        raw, kind, version = doc.raw, doc.requested_kind or doc.kind, doc.version
    try:
        if kind == "survey_json":
            pages, parsed, warnings = [], survey(raw), []
        else:
            kind, pages, parsed, warnings = parse_pdf(raw, kind, ocr)
            from .source_inference import extract

            proposed, notes = extract(engine.provider, pages, kind)
            parsed.extend(proposed)
            warnings.extend(notes)
        with db.write() as s:
            doc = s.get(Document, doc_id)
            if not doc or doc.version != version or doc.status != "processing":
                return
            old = list(
                s.scalars(
                    select(SourceItem).where(
                        SourceItem.document_id == doc.id, SourceItem.status != "superseded"
                    )
                )
            )
            by_key = {(v.locator, v.field, v.relation): v for v in old}
            seen = set()
            doc.kind, doc.pages, doc.warnings, doc.version = kind, pages, warnings, version + 1
            for row in parsed:
                key = (row.locator, row.field, row.relation)
                if key in seen:
                    continue
                seen.add(key)
                prior = by_key.get(key)
                if prior and (
                    prior.provenance.startswith("user_")
                    and prior.relation == row.relation
                    or prior.value == row.value
                    and prior.provenance == row.provenance
                    and prior.excerpt == row.excerpt
                ):
                    continue
                if prior:
                    retire(s, prior)
                item = SourceItem(document_id=doc.id, version=doc.version, **row.model_dump())
                s.add(item)
                if item.status == "active":
                    publish(s, engine, doc, item)
            for key, prior in by_key.items():
                if key not in seen and (
                    kind != "survey_json" or not prior.provenance.startswith("user_")
                ):
                    retire(s, prior)
            if not version:
                msg = working.add_message(
                    s,
                    s.get(Conversation, doc.journal_id),
                    "user",
                    "Imported " + doc.filename,
                    details={"document_id": doc.id, "locator": "document"},
                )
                episodes.form(
                    s,
                    msg,
                    EpisodeProposal(
                        summary=msg.content,
                        quote=msg.content,
                        message_id=msg.id,
                        topic=doc.filename[:150],
                        kind="study",
                    ),
                )
            doc.status = "ready"
    except Exception:
        with db.write() as s:
            doc = s.get(Document, doc_id)
            if doc and doc.version == version and doc.status == "processing":
                doc.status = "failed"
                doc.warnings = ["Parsing failed. Check file readability or classification, then retry."]


def confirm_fields(s, engine, doc, fields):
    if doc.kind != "survey_json" or doc.status != "ready":
        raise HTTPException(409, "Wait for a parsed survey")
    for edit in fields:
        prior = s.scalar(
            select(SourceItem).where(
                SourceItem.document_id == doc.id,
                SourceItem.locator == edit.pointer,
                SourceItem.status != "superseded",
            )
        )
        field = prior.field if prior else edit.pointer.lstrip("/")
        if not prior and mapping(field)[0] == "SURVEY_FIELD":
            raise HTTPException(422, "Unknown optional field")
        value = edit.value
        if prior and prior.provenance.startswith("user_") and prior.value["raw"] == value:
            continue
        if field == "cpi" and (
            isinstance(value, bool)
            or not str(value).replace(".", "", 1).isdigit()
            or not 0 <= float(value) <= 10
        ):
            raise HTTPException(422, "CPI must be between 0 and 10")
        if prior:
            retire(s, prior)
        rel = mapping(field)[0]
        prov = (
            "user_self_report"
            if rel == "HAS_REPORTED_SKILL_LEVEL"
            else "user_corrected"
            if prior and prior.value.get("raw") != value
            else "user_confirmed"
        )
        active = (
            value is not None
            and value != ""
            and not (isinstance(value, bool) and not value and rel == "HAS_GOAL")
            and rel != "IDENTIFIER"
            and field not in ("respondent_id", "roll_number", "roll_no", "student_id")
        )
        row = entry(
            field,
            value,
            edit.pointer,
            prov,
            "active" if active else "unselected",
            rel,
            datatype=type(value).__name__,
            meaning="not_selected"
            if value is False and rel == "HAS_GOAL"
            else "missing"
            if value is None
            else "confirmed",
        )
        doc.version += 1
        item = SourceItem(document_id=doc.id, version=doc.version, **row.model_dump())
        s.add(item)
        if active:
            publish(s, engine, doc, item, True)
    s.flush()


def detach_shared(s, cid):
    mids = select(Message.id).where(Message.conversation_id == cid)
    for event in s.scalars(select(Event).where(Event.source_id.in_(mids))):
        others = list(
            s.scalars(
                select(EventRevision).where(
                    EventRevision.event_id == event.id, EventRevision.source_id.not_in(mids)
                )
            )
        )
        support = next(
            (
                r
                for r in others
                if r.snapshot.get("local_date") == event.local_date
                and r.snapshot.get("title") == event.title
            ),
            None,
        )
        if support:
            event.source_id = support.source_id
            for revision in s.scalars(
                select(EventRevision).where(
                    EventRevision.event_id == event.id, EventRevision.source_id.in_(mids)
                )
            ):
                s.delete(revision)
            for candidate in s.scalars(
                select(Candidate).where(Candidate.event_id == event.id, Candidate.source_id.in_(mids))
            ):
                candidate.event_id = None
    s.flush()
    linked = list(s.scalars(select(Evidence).where(Evidence.message_id.in_(mids))))
    for e in linked:
        if s.scalar(
            select(Evidence.id).where(
                Evidence.memory_id == e.memory_id, Evidence.message_id.not_in(mids)
            )
        ):
            s.delete(e)
    s.flush()
