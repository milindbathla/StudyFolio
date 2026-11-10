import hashlib
import re
import threading
from datetime import timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import func, literal_column, select

from ..calendar import service as calendar
from ..cdf import retrieve
from ..contracts import FactProposal, Query
from ..db import one, row, settings
from ..knowledge import LocalGraph, question
from ..models import (
    Assertion,
    Candidate,
    Conversation,
    Event,
    EventRevision,
    Evidence,
    Job,
    Memory,
    Message,
    Semantic,
    Suppression,
    now,
)
from ..provider import ProviderFailure
from ..source_models import Document, SourceItem
from ..vectors import changed
from . import episodes, facts, retrieval, working
from .extraction import grounded, normal, rule_episodes, rule_facts


def queue(s, thread, kind, key, msg=None):
    existing = s.scalar(select(Job).where(Job.key == key))
    if existing:
        return existing
    job = Job(conversation_id=thread.id, kind=kind, key=key, message_id=msg.id if msg else None)
    s.add(job)
    s.flush()
    return job


def fingerprint(path, val, scope=""):
    return hashlib.sha256(f"{path}|{normal(val)}|{normal(scope)}".encode()).hexdigest()


class MemoryOrchestrator:
    def __init__(self, db, cfg, vectors, provider):
        self.db, self.cfg, self.vectors, self.provider = db, cfg, vectors, provider
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self._chat_lock = threading.Lock()
        self.thread = None
        self.index_thread = None
        self.source_thread = None
        self.graph = LocalGraph(cfg.db_url)

    def start(self):
        with self.db.write() as s:
            for doc in s.scalars(select(Document).where(Document.status == "processing")):
                doc.status = "queued"
            for j in s.scalars(select(Job).where(Job.status == "running")):
                j.status = "queued"
        if self.cfg.worker:
            self.thread = threading.Thread(target=self.loop, daemon=True, name="learner-jobs")
            self.thread.start()
            self.index_thread = threading.Thread(
                target=self.index_loop, daemon=True, name="learner-index"
            )
            self.index_thread.start()
            self.source_thread = threading.Thread(
                target=self.source_loop, daemon=True, name="source-ingestion"
            )
            self.source_thread.start()

    def source_loop(self):
        import os

        from ..sources import parse_job

        while not self.stop_event.is_set():
            with self.db.sessions() as s:
                item = s.scalar(
                    select(Document.id)
                    .where(Document.status == "queued")
                    .order_by(Document.created_at)
                    .limit(1)
                )
            if item:
                parse_job(self, item, ocr=os.getenv("SOURCE_OCR", "false").lower() == "true")
            self.graph.sync(self.db)
            self.stop_event.wait(0.5 if item else 2)

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        for thread in (self.thread, self.index_thread, self.source_thread):
            if thread:
                thread.join()
        if self.graph.driver:
            self.graph.driver.close()

    def index_loop(self):
        while not self.stop_event.is_set():
            self.vectors.drain(self.db)
            self.stop_event.wait(2)

    def loop(self):
        consolidate_at = now() + timedelta(hours=1)
        while not self.stop_event.is_set():
            if now() >= consolidate_at:
                with self.db.write() as s:
                    for c in s.scalars(select(Conversation).where(Conversation.closed == False)):  # noqa: E712
                        self.request_reflection(s, c, "scheduled")
                consolidate_at = now() + timedelta(hours=1)
            if not self.run_one():
                self.wake.wait(1)
                self.wake.clear()

    def accept(self, s, p, m, **options):
        key = fingerprint(p.path, p.value, p.scope)
        if s.scalar(
            select(Suppression.id).where(Suppression.fingerprint == key, Suppression.message_id == m.id)
        ):
            return None
        return facts.accept(s, p, m, self.vectors, **options)

    def process(self, s, m, analysis=None):
        if m.details.get("document_id"):
            return
        for p in [*rule_facts(m), *(analysis.facts if analysis else [])]:
            self.accept(s, p, m)
        for e in rule_episodes(m):
            episodes.form(s, m, e)
        for e in analysis.episodes if analysis else []:
            episodes.form(s, m, e, from_model=True)
        calendar.extract(s, m, analysis.dates if analysis else [])
        m.status = "processed"

    def ingest(self, s, c, turn, at=None):
        if turn.request_key:
            prior = s.scalar(
                select(Message).where(
                    Message.conversation_id == c.id,
                    Message.request_key == turn.request_key,
                    Message.role == "user",
                )
            )
            if prior:
                if prior.content != turn.content:
                    raise HTTPException(409, "This request key belongs to different content")
                return prior
        if c.closed:
            raise HTTPException(409, "Reopen the conversation to add a message")
        m = working.add_message(s, c, "user", turn.content, at, key=turn.request_key)
        if c.title == "Untitled conversation":
            c.title = turn.content[:65]
        local_failed = False
        try:
            with s.begin_nested():
                self.process(s, m)
        except Exception:
            local_failed = True
        j = queue(s, c, "extract", "extract:" + m.id, m)
        if not self.provider.enabled and not local_failed:
            j.status = "done"
        else:
            m.status = "queued"
            if local_failed:
                j.error = "Local extraction deferred; original message retained"
        n = s.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == c.id, Message.role == "user")
        )
        if n % settings(s)["reflection_threshold"] == 0:
            self.request_reflection(s, c, "threshold")
        self.wake.set()
        return m

    def request_reflection(self, s, c, reason):
        if s.scalar(select(Document.id).where(Document.journal_id == c.id)):
            return None
        last = s.scalar(
            select(Message)
            .where(Message.conversation_id == c.id, Message.role == "user")
            .order_by(Message.created_at.desc(), Message.position.desc())
        )
        if not last:
            return None
        job = queue(s, c, "reflect", "reflect:" + c.id + ":" + last.id, last)
        if reason == "manual" and job.status in ("done", "failed"):
            job.status, job.attempts, job.available_at = "queued", 0, now()
        self.wake.set()
        return job

    def run_one(self):
        with self.db.write() as s:
            job = s.scalar(
                select(Job)
                .where(Job.status == "queued", Job.available_at <= now())
                .order_by(Job.created_at, literal_column("memory_processing_jobs.rowid"))
                .limit(1)
            )
            if not job:
                return False
            job.status = "running"
            job.attempts += 1
            jid = job.id
        try:
            self.execute_job(jid)
        except Exception as exc:
            with self.db.write() as s:
                j = s.get(Job, jid)
                if j:
                    j.error = (
                        "Provider unavailable or invalid result"
                        if isinstance(exc, ProviderFailure)
                        else "Processing failed; original evidence is retained"
                    )
                    j.status = "failed" if j.attempts >= 3 else "queued"
                    j.available_at = now() + timedelta(seconds=2**j.attempts)
                    if j.message_id and j.kind == "extract":
                        s.get(Message, j.message_id).status = j.status
        return True

    def execute_job(self, jid):
        with self.db.sessions() as s:
            job = s.get(Job, jid)
            if not job:
                return
            conv = s.get(Conversation, job.conversation_id)
            m = s.get(Message, job.message_id)
            if job.kind == "reflect":
                stmt = select(Message).where(
                    Message.conversation_id == conv.id,
                    Message.role == "user",
                    (Message.created_at < m.created_at)
                    | ((Message.created_at == m.created_at) & (Message.position <= m.position)),
                )
                if conv.reflected_through:
                    stmt = stmt.where(
                        (Message.created_at > conv.reflected_through)
                        | (
                            (Message.created_at == conv.reflected_through)
                            & (Message.position > conv.reflected_position)
                        )
                    )
                batch = list(s.scalars(stmt.order_by(Message.created_at, Message.position).limit(17)))
                chunk = batch[:16]
                payload = {
                    "messages": [{"id": v.id, "content": v.content[:2400]} for v in chunk],
                    "current": [
                        {
                            "id": a.id,
                            "path": a.path,
                            "value": a.value,
                            "scope": a.scope,
                            "manual": a.manual,
                        }
                        for a in s.scalars(
                            select(Assertion)
                            .where(Assertion.status == "active")
                            .order_by(Assertion.manual.desc(), Assertion.updated_at.desc())
                            .limit(36)
                        )
                    ],
                    "memories": [
                        x.content
                        for x in s.scalars(
                            select(Memory)
                            .join(Evidence)
                            .where(
                                Evidence.message_id.in_([v.id for v in chunk]), Memory.status == "active"
                            )
                            .limit(24)
                        )
                    ],
                }
            else:
                payload = {"id": m.id, "content": m.content}
            kind = job.kind
        analysis = (
            self.provider.analyze(payload) if self.provider.enabled and kind == "extract" else None
        )
        reflection = (
            self.provider.reflect(payload)
            if self.provider.enabled and kind == "reflect" and chunk
            else None
        )
        with self.db.write() as s:
            job = s.get(Job, jid)
            if not job:
                return
            if kind == "extract":
                self.process(s, s.get(Message, job.message_id), analysis)
            else:
                c = s.get(Conversation, job.conversation_id)
                for old in chunk:
                    self.process(s, s.get(Message, old.id))
                for p in reflection.patches if reflection else []:
                    evidence = (
                        s.get(Message, p.message_id)
                        if any(x.id == p.message_id for x in chunk)
                        else None
                    )
                    if not grounded(p, evidence) or p.operation == "NO_CHANGE":
                        continue
                    a = s.get(Assertion, p.target_id) if p.target_id else None
                    if p.operation in ("REMOVE", "REPLACE", "SUPERSEDE") and (
                        not a or a.path != p.path or a.scope != normal(p.scope) or a.manual
                    ):
                        continue
                    if p.operation == "REMOVE":
                        if (
                            p.correction
                            and p.origin == "explicit"
                            and normal(a.value) in normal(p.quote)
                            and re.search(r"\b(no longer|do not|don't|remove|forget)\b", p.quote, re.I)
                        ):
                            facts.link(s, a, evidence, p.quote)
                            facts.decide(s, a, False)
                    else:
                        self.accept(s, p, evidence, target=s.get(Semantic, a.semantic_id) if a else None)
                if chunk:
                    cursor = (chunk[-1].created_at, chunk[-1].position)
                    if not c.reflected_through or cursor > (c.reflected_through, c.reflected_position):
                        c.reflected_through, c.reflected_position = cursor
                if len(batch) > 16:
                    job.status = "queued"
                    job.attempts = 0
                    return
            job.status, job.error = "done", None

    def search(self, s, q, at=None):
        thread = one(s, Conversation, q.conversation_id) if q.conversation_id else None
        return retrieval.inspect(s, q, thread, self.cfg, self.vectors, at)

    def calendar_answer(self, s, question, at):
        q = question.lower()
        if not re.search(
            r"\b(deadlines?|assignments?|exams?|quizzes|quiz|calendar|due|events?)\b", q
        ) or not ("?" in q or re.search(r"\b(show|list|upcoming|overdue|which|when)\b", q)):
            return None
        tz = ZoneInfo(settings(s)["timezone"])
        today = at.astimezone(tz).date()
        start = end = None
        if "week" in q:
            start = (
                today - timedelta(days=today.weekday()) + timedelta(days=7 if "next week" in q else 0)
            )
            end = start + timedelta(days=6)
        category = next(
            (v for k, v in [("assignment", "assignment"), ("exam", "exam"), ("quiz", "quiz")] if k in q),
            None,
        )
        rows = calendar.events_in_window(
            s,
            start,
            end,
            category,
            upcoming=not start and "overdue" not in q,
            overdue="overdue" in q,
            at=at,
        )
        return [
            {
                "id": e.id,
                "title": e.title,
                "date": e.start_utc.astimezone(tz).isoformat(timespec="minutes")
                if e.start_utc
                else e.local_date,
                "source_id": e.source_id,
            }
            for e in rows[:30]
        ]

    def chat(self, turn):
        # Serialize duplicate request keys across the provider boundary, without holding a SQLite write lock.
        from ..cdf import intent
        from ..source_inference import refine

        refinement = (
            refine(self.provider, turn.content)
            if question(turn.content) and intent(turn.content)[0] == "general_conversation"
            else None
        )
        with self.chat_lock:
            with self.db.write() as s:
                c = one(s, Conversation, turn.conversation_id)
                m = self.ingest(s, c, turn)
                if turn.request_key:
                    old = s.scalar(
                        select(Message).where(
                            Message.conversation_id == c.id,
                            Message.request_key == turn.request_key,
                            Message.role == "assistant",
                        )
                    )
                    if old:
                        return {"user": row(m), "assistant": row(old)}
                query = Query(query=turn.content[:2000], conversation_id=c.id)
                ctx = {"selected": []}
                trace = (
                    retrieve(s, self, m.content, refinement)
                    if question(m.content) or re.match(r"^(show|list|recall|tell me)\b", m.content, re.I)
                    else None
                )
                exact = (
                    trace
                    and trace["answer"]
                    and trace["intent"] not in ("episodic_history_lookup", "temporal_event_lookup")
                )
                if exact:
                    ctx["selected"] = [
                        {
                            "id": r["id"],
                            "layer": "source" if r["evidence"][0].get("document_id") else "semantic",
                            "content": r["value"],
                            "score": 0,
                            "reasons": ["structured lookup"],
                            "evidence": r["evidence"],
                            "timestamp": r["evidence"][0]["timestamp"],
                        }
                        for r in trace["selected"]
                    ]
                if not exact:
                    ctx = self.search(s, query)
                dates = self.calendar_answer(s, m.content, m.created_at)
                user, mid, cid = row(m), m.id, c.id
            mode = "offline"
            if exact:
                reply = trace["answer"]
            elif dates is not None:
                reply = (
                    "\n".join(f"• {e['title']} — {e['date']}" for e in dates)
                    or "There are no confirmed calendar events matching that request."
                )
            else:
                reply = self.offline_reply(turn.content, ctx)
            if self.provider.enabled and not exact:
                try:
                    reply = self.provider.chat(
                        {"query": turn.content, "context": ctx["selected"], "confirmed_calendar": dates}
                    )
                    mode = "model"
                except ProviderFailure:
                    mode = "provider unavailable"
            with self.db.write() as s:
                c = one(s, Conversation, cid)
                if not s.get(Message, mid):
                    raise HTTPException(409, "Source turn was removed")
                if (
                    any(
                        not s.get(Message, r["message_id"])
                        for h in ctx["selected"]
                        for r in h["evidence"]
                    )
                    or any(
                        h["layer"] != "working"
                        and (
                            (mem := s.get(SourceItem if h["layer"] == "source" else Memory, h["id"]))
                            is None
                            or mem.status != "active"
                        )
                        for h in ctx["selected"]
                    )
                    or any(not s.get(Event, e["id"]) for e in dates or [])
                ):
                    ctx = self.search(s, query)
                    dates = self.calendar_answer(s, turn.content, now())
                    reply = "The underlying records changed while composing this reply. Ask again to use the current sources."
                    mode = "sources changed"
                response = working.add_message(
                    s,
                    c,
                    "assistant",
                    reply,
                    key=turn.request_key,
                    details={"mode": mode, "sources": ctx["selected"], "calendar": dates or []},
                )
                return {"user": user, "assistant": row(response)}

    @property
    def chat_lock(self):
        return self._chat_lock

    def offline_reply(self, query, ctx):
        if not query.rstrip().endswith("?") and not re.match(
            r"(?i)(show|list|recall|what|which|when|tell me)", query
        ):
            return "Saved this turn. You can review extracted memories in Memory Explorer and academic dates in Calendar suggestions."
        hits = [h for h in ctx["selected"] if h["layer"] != "working" or "user" in h["reasons"]]
        if not hits:
            return "I couldn’t find a matching source in your local workspace."
        return "From your saved conversations:\n" + "\n".join(f"• {h['content']}" for h in hits[:4])

    def manual_patch(self, s, p):
        a = one(s, Assertion, p.target_id) if p.target_id else None
        if a and a.path != p.path:
            raise HTTPException(422, "Target does not belong to this field")
        if p.operation == "NO_CHANGE":
            return a
        if p.operation == "REMOVE":
            return facts.decide(s, a, False)
        journal = s.scalar(
            select(Conversation).where(Conversation.id == "00000000-0000-4000-8000-000000000002")
        )
        if not journal:
            journal = Conversation(id="00000000-0000-4000-8000-000000000002", title="Profile edits")
            s.add(journal)
            s.flush()
        m = working.add_message(s, journal, "user", f"Profile edit · {p.path}: {p.value}")
        val = FactProposal(
            path=p.path,
            value=p.value,
            quote=p.value,
            message_id=m.id,
            scope=p.scope or (a.scope if a else ""),
            confidence=1,
            correction=True,
        )
        return self.accept(s, val, m, manual=True, target=s.get(Semantic, a.semantic_id) if a else None)

    def forget_memory(self, s, mem, suppress=True):
        if suppress:
            for item in s.scalars(
                select(SourceItem).where(SourceItem.memory_id == getattr(mem, "semantic_id", mem.id))
            ):
                item.status = "rejected"
        if isinstance(mem, Assertion):
            mem = s.get(Semantic, mem.semantic_id)
        if isinstance(mem, Semantic):
            a = facts.assertion_for(s, mem)
            if a:
                s.delete(a)
                s.flush()
            if suppress:
                for ref in facts.sources(s, mem.id):
                    s.add(
                        Suppression(
                            message_id=ref["message_id"],
                            fingerprint=fingerprint(mem.predicate, mem.value, mem.scope),
                        )
                    )
        changed(s, mem, "delete")
        s.delete(mem)
        s.flush()

    def forget_conversation(self, s, c):
        from ..sources import detach_shared

        if s.scalar(select(Document.id).where(Document.journal_id == c.id)):
            detach_shared(s, c.id)
        mids = set(s.scalars(select(Message.id).where(Message.conversation_id == c.id)))
        related = set(s.scalars(select(Evidence.memory_id).where(Evidence.message_id.in_(mids))))
        for mem_id in related:
            mem = s.get(Memory, mem_id)
            if mem and not isinstance(mem, Assertion):
                self.forget_memory(s, mem, False)
        # Purge the whole derived event, including a reschedule sourced from another thread.
        event_ids = set(
            s.scalars(select(EventRevision.event_id).where(EventRevision.source_id.in_(mids)))
        )
        candidates = list(s.scalars(select(Candidate)))
        affected = {v.id for v in candidates if v.source_id in mids}
        while True:
            size = len(affected) + len(event_ids)
            event_ids.update(v.event_id for v in candidates if v.id in affected and v.event_id)
            affected.update(
                v.id
                for v in candidates
                if v.target_id in event_ids
                or v.event_id in event_ids
                or affected.intersection(v.parsed.get("prior_candidates", []))
                or v.parsed.get("duplicate_of") in affected
                or event_ids.intersection(v.parsed.get("possible_targets", []))
            )
            if len(affected) + len(event_ids) == size:
                break
        for v in candidates:
            if v.id in affected:
                s.delete(v)
        s.flush()
        for event_id in event_ids:
            e = s.get(Event, event_id)
            if e:
                s.delete(e)
        for msg in s.scalars(
            select(Message).where(Message.role == "assistant", Message.conversation_id != c.id)
        ):
            if any(
                h["id"] in related or any(ref["message_id"] in mids for ref in h["evidence"])
                for h in msg.details.get("sources", [])
            ) or any(v["id"] in event_ids for v in msg.details.get("calendar", [])):
                s.delete(msg)
        s.delete(c)
        s.flush()
