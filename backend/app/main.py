import logging
import os
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from sqlalchemy import func, select
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .calendar import service as cal
from .config import ROOT, Config
from .contracts import (
    Chat,
    CsvImport,
    EditThread,
    EventInput,
    ManualPatch,
    NewThread,
    Query,
    Rebuild,
    Review,
    SemanticEdit,
    SettingsPatch,
    Turn,
)
from .db import Database, one, row, settings
from .memory import facts, working
from .memory.orchestrator import MemoryOrchestrator, queue
from .models import (
    Assertion,
    Candidate,
    Conversation,
    Episode,
    Event,
    Job,
    Memory,
    Message,
    PersonaRevision,
    Semantic,
    Settings,
    VectorChange,
    now,
)
from .provider import Provider
from .responses import (
    CalendarRecord,
    ChatReply,
    Inspection,
    MemoryRecord,
    MessageRecord,
    PersonaView,
    Source,
    ThreadRecord,
)
from .vectors import VectorIndex, changed


def create_app(cfg=None, provider=None, vectors=None):
    cfg = cfg or Config()
    db = Database(cfg)
    provider = provider or Provider(cfg)
    vectors = vectors or VectorIndex(cfg)
    engine = MemoryOrchestrator(db, cfg, vectors, provider)

    @asynccontextmanager
    async def lifespan(app):
        db.initialize()
        engine.start()
        try:
            yield
        finally:
            engine.stop()
            vectors.close()
            db.engine.dispose()

    app = FastAPI(
        title="Learner Memory & Persona Intelligence System", version="1.0.0", lifespan=lifespan
    )
    app.state.db, app.state.memory, app.state.vectors = db, engine, vectors
    local_origins = [
        f"http://{host}:{port}"
        for host in ("localhost", "127.0.0.1")
        for port in (5173, 8000, 4173, int(os.getenv("APP_PORT", "8000")))
    ]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=local_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        if (
            request.url.path == "/api/v1/sources/upload"
            and (length := request.headers.get("content-length", "")).isdigit()
            and int(length) > 16 * 1024 * 1024 + 65536
        ):
            return JSONResponse({"detail": "Upload exceeds 16 MiB"}, status_code=413)
        if (
            request.method not in ("GET", "HEAD", "OPTIONS")
            and (origin := request.headers.get("origin"))
            and origin not in local_origins
        ):
            return JSONResponse({"detail": "Unrecognized browser origin"}, status_code=403)
        try:
            return await call_next(request)
        except Exception as exc:
            logging.getLogger("studyfolio").error("Local request failed (%s)", type(exc).__name__)
            return JSONResponse(
                {"detail": "Local operation failed. Check service status or retry."}, status_code=500
            )

    @app.exception_handler(ValueError)
    async def invalid_value(request, exc):
        return JSONResponse(
            {"detail": exc.errors()[0]["msg"] if isinstance(exc, ValidationError) else str(exc)[:160]},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unexpected(request, exc):
        return JSONResponse(
            {"detail": "Local operation failed. Check service status or retry."}, status_code=500
        )

    def read():
        with db.sessions() as s:
            yield s

    def write():
        with db.write() as s:
            yield s

    r = APIRouter(prefix="/api/v1")

    @r.get("/health")
    def health():
        return {"status": "ok", "service": "learner-memory"}

    @r.get("/health/details")
    def details(s=Depends(read)):
        return {
            "status": "ok",
            "mode": "model" if provider.enabled else "offline",
            "model": provider.model or None,
            "vector_status": vectors.state,
            "vector_error_type":getattr(vectors,"error_kind",None),
            "pending_vectors": s.scalar(select(func.count()).select_from(VectorChange)),
            "storage": "SQLite",
            "calendar": "local",
        }

    @r.get("/settings")
    def get_settings(s=Depends(read)):
        return settings(s) | details(s)

    @r.patch("/settings")
    def update_settings(p: SettingsPatch, s=Depends(write, scope="function")):
        config = s.scalar(select(Settings))
        config.values = settings(s) | p.model_dump(exclude_none=True)
        return config.values | details(s)

    @r.get("/conversations", response_model=list[ThreadRecord])
    def threads(q: str = "", s=Depends(read)):
        stmt = select(Conversation)
        if q:
            stmt = stmt.where(
                Conversation.title.contains(q, autoescape=True)
                | Conversation.id.in_(
                    select(Message.conversation_id).where(Message.content.contains(q, autoescape=True))
                )
            )
        return [row(c) for c in s.scalars(stmt.order_by(Conversation.updated_at.desc()))]

    @r.post("/conversations", status_code=201, response_model=ThreadRecord)
    def new_thread(p: NewThread, s=Depends(write, scope="function")):
        c = Conversation(title=p.title)
        s.add(c)
        s.flush()
        return row(c)

    @r.get("/conversations/{cid}", response_model=ThreadRecord)
    def thread(cid: str, s=Depends(read)):
        return row(one(s, Conversation, cid))

    @r.patch("/conversations/{cid}", response_model=ThreadRecord)
    def patch_thread(cid: str, p: EditThread, s=Depends(write, scope="function")):
        c = one(s, Conversation, cid)
        for k, v in p.model_dump(exclude_none=True).items():
            setattr(c, k, v)
        if p.closed:
            engine.request_reflection(s, c, "close")
        return row(c)

    @r.delete("/conversations/{cid}", status_code=204)
    def delete_thread(cid: str):
        with db.write() as s:
            engine.forget_conversation(s, one(s, Conversation, cid))
        vectors.drain(db)
        return Response(status_code=204)

    @r.get("/conversations/{cid}/messages", response_model=list[MessageRecord])
    def messages(cid: str, q: str = "", s=Depends(read)):
        return [
            row(m)
            for m in working.get_conversation_context(s, one(s, Conversation, cid))
            if q.casefold() in m.content.casefold()
        ]

    @r.get("/conversations/{cid}/context")
    def conversation_context(cid: str, s=Depends(read)):
        c = one(s, Conversation, cid)
        recent = working.get_recent_context(s, c)
        topics = [
            t
            for e in s.scalars(
                select(Episode)
                .where(Episode.conversation_id == cid)
                .order_by(Episode.end_time.desc())
                .limit(3)
            )
            for t in e.topics
        ]
        last = next((m for m in reversed(recent) if m.role == "user"), None)
        return {
            "state": "closed" if c.closed else "open",
            "recent": [row(m) for m in recent],
            "older_excerpts": working.compact_context(s, c),
            "topics": list(dict.fromkeys(topics)),
            "intent": "question"
            if last and last.content.endswith("?")
            else "statement"
            if last
            else None,
        }

    @r.post("/conversations/{cid}/messages", status_code=201, response_model=MessageRecord)
    def add_message(cid: str, p: Turn, s=Depends(write, scope="function")):
        return row(engine.ingest(s, one(s, Conversation, cid), p))

    @r.post("/conversations/{cid}/reflect")
    def reflect_thread(cid: str, s=Depends(write, scope="function")):
        job = engine.request_reflection(s, one(s, Conversation, cid), "manual")
        return {"jobs": [job.id] if job else []}

    def reprocess(s, c):
        from .source_models import Document

        if s.scalar(select(Document.id).where(Document.journal_id == c.id)):
            return 0
        count = 0
        for m in working.get_conversation_context(s, c):
            if m.role != "user":
                continue
            job = queue(s, c, "extract", "extract:" + m.id, m)
            job.status, job.error, job.attempts, job.available_at = "queued", None, 0, now()
            count += 1
        c.reflected_through = None
        c.reflected_position = 0
        engine.request_reflection(s, c, "manual")
        engine.wake.set()
        return count

    @r.post("/conversations/{cid}/reprocess")
    def reprocess_thread(cid: str, s=Depends(write, scope="function")):
        return {"queued": reprocess(s, one(s, Conversation, cid))}

    @r.post("/chat", response_model=ChatReply)
    def chat(p: Chat):
        return engine.chat(p)

    @r.get("/memory/short-term", response_model=list[MessageRecord])
    def short_term(conversation_id: str | None = None, s=Depends(read)):
        cs = (
            [one(s, Conversation, conversation_id)]
            if conversation_id
            else s.scalars(select(Conversation).order_by(Conversation.updated_at.desc()))
        )
        return [row(m) for c in cs for m in working.restore_after_restart(s, c)]

    @r.delete("/memory/short-term/{cid}", status_code=204)
    def clear_working(cid: str, s=Depends(write, scope="function")):
        working.clear_working_context(one(s, Conversation, cid))
        return Response(status_code=204)

    def memory_list(s, cls, status, q):
        stmt = select(cls).order_by(cls.created_at.desc())
        if status:
            stmt = stmt.where(cls.status == status)
        if q:
            stmt = stmt.where(cls.content.contains(q, autoescape=True))
        return [facts.describe(s, v) for v in s.scalars(stmt)]

    @r.get("/memory/episodes", response_model=list[MemoryRecord])
    def episodes(status: str = "", q: str = "", s=Depends(read)):
        return memory_list(s, Episode, status, q)

    @r.get("/memory/semantic", response_model=list[MemoryRecord])
    def semantic(status: str = "", q: str = "", s=Depends(read)):
        return memory_list(s, Semantic, status, q)

    @r.post("/memory/search", response_model=Inspection)
    def search(p: Query, s=Depends(read)):
        return engine.search(s, p)

    @r.get("/debug/retrieval", response_model=Inspection)
    def debug(query: str, conversation_id: str | None = None, s=Depends(read)):
        return engine.search(s, Query(query=query, conversation_id=conversation_id))

    @r.post("/memory/reflect")
    @r.post("/persona/reflect")
    def reflect_all(s=Depends(write, scope="function")):
        jobs = [
            j.id
            for c in s.scalars(select(Conversation))
            if (j := engine.request_reflection(s, c, "manual"))
        ]
        return {"jobs": jobs}

    @r.post("/memory/rebuild")
    def rebuild(p: Rebuild = Rebuild()):
        with db.write() as s:
            count = sum(reprocess(s, c) for c in s.scalars(select(Conversation))) if p.history else 0
            total = 0
            for mem in s.scalars(select(Memory).where(Memory.layer.in_(["episodic", "semantic"]))):
                changed(s, mem, "upsert" if mem.status == "active" else "delete")
                total += 1
            from .source_models import SourceItem

            for item in s.scalars(select(SourceItem).where(SourceItem.status == "active")):
                pending = s.scalar(select(VectorChange).where(VectorChange.memory_id == item.id))
                if not pending:
                    s.add(VectorChange(memory_id=item.id, layer="document_chunks", action="upsert"))
                total += 1
        vectors.drain(db, limit=32, repair=True)
        return {"indexed_or_queued": total, "history_jobs": count, "vector_status": vectors.state}

    @r.patch("/memory/semantic/{mid}", response_model=MemoryRecord)
    def edit_semantic(mid: str, p: SemanticEdit, s=Depends(write, scope="function")):
        f = one(s, Semantic, mid)
        a = facts.assertion_for(s, f)
        if p.value:
            a = engine.manual_patch(
                s,
                ManualPatch(
                    path=a.path, operation="REPLACE", target_id=a.id, value=p.value, scope=a.scope
                ),
            )
            f = s.get(Semantic, a.semantic_id)
        if p.status == "archived":
            facts.transition(s, f, "archived", now())
            facts.transition(s, a, "archived", now())
        elif p.status:
            facts.decide(s, a, p.status == "active")
        return facts.describe(s, f)

    @r.delete("/memory/semantic/{mid}", status_code=204)
    def del_memory(mid: str):
        with db.write() as s:
            engine.forget_memory(s, one(s, Semantic, mid))
        vectors.drain(db)
        return Response(status_code=204)

    @r.get("/memory/{mid}/evidence", response_model=list[Source])
    def evidence(mid: str, s=Depends(read)):
        return facts.sources(s, one(s, Memory, mid).id)

    @r.get("/persona", response_model=PersonaView)
    def persona(s=Depends(read)):
        return facts.profile(s)

    @r.get("/persona/history")
    def history(assertion_id: str | None = None, s=Depends(read)):
        stmt = select(PersonaRevision).order_by(PersonaRevision.created_at.desc())
        if assertion_id:
            stmt = stmt.where(PersonaRevision.assertion_id == assertion_id)
        return [row(v) for v in s.scalars(stmt)]

    @r.patch("/persona")
    def patch_persona(p: ManualPatch, s=Depends(write, scope="function")):
        a = engine.manual_patch(s, p)
        return facts.describe(s, a) if a else {"operation": "NO_CHANGE"}

    @r.post("/persona/assertions/{aid}/confirm", response_model=MemoryRecord)
    def confirm_assertion(aid: str, s=Depends(write, scope="function")):
        return facts.describe(s, facts.decide(s, one(s, Assertion, aid), True))

    @r.post("/persona/assertions/{aid}/reject", response_model=MemoryRecord)
    def reject_assertion(aid: str, s=Depends(write, scope="function")):
        return facts.describe(s, facts.decide(s, one(s, Assertion, aid), False))

    @r.get("/calendar/events", response_model=list[CalendarRecord])
    def events(
        start: date | None = None,
        end: date | None = None,
        category: str = "",
        q: str = "",
        overdue: bool = False,
        s=Depends(read),
    ):
        return [
            cal.view(s, e) for e in cal.events_in_window(s, start, end, category, q, overdue=overdue)
        ]

    @r.get("/calendar/upcoming", response_model=list[CalendarRecord])
    def upcoming(s=Depends(read)):
        return [cal.view(s, e) for e in cal.events_in_window(s, upcoming=True)]

    @r.post("/calendar/events", status_code=201, response_model=CalendarRecord)
    def new_event(p: EventInput, s=Depends(write, scope="function")):
        return cal.view(s, cal.create(s, p))

    @r.get("/calendar/events/{eid}", response_model=CalendarRecord)
    def event(eid: str, s=Depends(read)):
        return cal.view(s, one(s, Event, eid))

    @r.patch("/calendar/events/{eid}", response_model=CalendarRecord)
    def patch_event(eid: str, p: dict, s=Depends(write, scope="function")):
        e = one(s, Event, eid)
        zone = ZoneInfo(e.timezone)
        data = dict(
            title=e.title,
            category=e.category,
            date=e.local_date,
            timezone=e.timezone,
            description=e.description,
            time=e.start_utc.astimezone(zone).time() if e.start_utc else None,
            end_time=e.end_utc.astimezone(zone).time() if e.end_utc else None,
        )
        return cal.view(s, cal.edit(s, e, EventInput.model_validate(data | p)))

    @r.delete("/calendar/events/{eid}", status_code=204)
    def del_event(eid: str, s=Depends(write, scope="function")):
        e = one(s, Event, eid)
        for c in s.scalars(
            select(Candidate).where((Candidate.event_id == eid) | (Candidate.target_id == eid))
        ):
            c.status = "rejected"
        s.delete(e)
        return Response(status_code=204)

    @r.get("/calendar/candidates", response_model=list[CalendarRecord])
    def candidates(status: str = "proposed", s=Depends(read)):
        return [
            cal.view(s, c)
            for c in s.scalars(
                select(Candidate).where(Candidate.status == status).order_by(Candidate.created_at.desc())
            )
        ]

    @r.post("/calendar/candidates/{candidate_id}/confirm", response_model=CalendarRecord)
    def confirm(candidate_id: str, p: Review = Review(), s=Depends(write, scope="function")):
        c = one(s, Candidate, candidate_id)
        if any(
            (old := s.get(Candidate, i)) and old.status == "proposed"
            for i in c.parsed.get("ambiguous_proposals", [])
        ):
            raise HTTPException(409, "Resolve the matching earlier suggestions first")
        return cal.view(s, cal.confirm(s, c, p))

    @r.post("/calendar/candidates/{candidate_id}/reject", response_model=CalendarRecord)
    def reject(candidate_id: str, s=Depends(write, scope="function")):
        c = one(s, Candidate, candidate_id)
        if c.status not in ("proposed", "rejected"):
            raise HTTPException(409, "Suggestion is no longer pending")
        c.status = "rejected"
        return cal.view(s, c)

    @r.get("/calendar/export.ics")
    def export_ics(s=Depends(read)):
        return Response(
            cal.ics(s),
            media_type="text/calendar",
            headers={"Content-Disposition": 'attachment; filename="studyfolio.ics"'},
        )

    @r.post("/calendar/import/csv")
    def upload(p: CsvImport, s=Depends(write, scope="function")):
        return cal.import_csv(s, p.content)

    @r.get("/jobs")
    def jobs(s=Depends(read)):
        return [row(j) for j in s.scalars(select(Job).order_by(Job.created_at.desc()).limit(200))]

    @r.get("/jobs/{jid}")
    def job(jid: str, s=Depends(read)):
        return row(one(s, Job, jid))

    @r.post("/jobs/{jid}/retry")
    def retry(jid: str, s=Depends(write, scope="function")):
        j = one(s, Job, jid)
        if j.status != "running":
            j.status, j.attempts, j.error, j.available_at = "queued", 0, None, now()
        engine.wake.set()
        return row(j)

    @r.get("/data/export")
    def export_data(s=Depends(read)):
        from fastapi.encoders import jsonable_encoder

        payload = {
            "settings": settings(s),
            "conversations": threads("", s),
            "messages": [row(m) for m in s.scalars(select(Message))],
            "memories": [facts.describe(s, m) for m in s.scalars(select(Memory))],
            "persona_history": history(None, s),
            "events": events(s=s),
            "candidates": [cal.view(s, c) for c in s.scalars(select(Candidate))],
        }
        return JSONResponse(
            jsonable_encoder(payload),
            headers={"Content-Disposition": 'attachment; filename="studyfolio.json"'},
        )

    @r.delete("/data", status_code=204)
    def erase(confirm: str):
        if confirm != "DELETE":
            raise HTTPException(422, "Type DELETE to erase the local workspace")
        with db.write() as s:
            for c in list(s.scalars(select(Conversation))):
                engine.forget_conversation(s, c)
            for e in s.scalars(select(Event)):
                s.delete(e)
        vectors.drain(db, limit=100000)
        return Response(status_code=204)

    from .source_api import router as source_router

    app.include_router(source_router(engine, read, write))
    app.include_router(r)
    dist = ROOT / "frontend" / "dist"
    if dist.is_dir():

        class SPA(StaticFiles):
            async def get_response(self, path, scope):
                from starlette.exceptions import HTTPException as StarletteHTTPException

                try:
                    return await super().get_response(path, scope)
                except StarletteHTTPException as exc:
                    if (
                        exc.status_code == 404
                        and not path.startswith(("api/", "assets/"))
                        and "." not in Path(path).name
                    ):
                        return await super().get_response("index.html", scope)
                    raise

        app.mount("/", SPA(directory=dist, html=True), name="workspace")
    return app


app = create_app()
