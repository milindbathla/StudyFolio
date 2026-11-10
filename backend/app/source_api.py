from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select

from .cdf import retrieve
from .contracts import Query
from .db import one, row
from .knowledge import catalog, ends
from .models import Conversation, Memory, VectorChange
from .source_models import Document, GraphChange, SourceItem
from .source_parse import FIELDS, Kind
from .sources import confirm_fields, receive


class SourceInfo(BaseModel):
    id: str
    filename: str
    kind: str
    status: str
    version: int
    digest: str
    warnings: list[str]


class ItemInfo(BaseModel):
    id: str
    document_id: str
    locator: str
    field: str
    relation: str
    subject: str
    value: dict
    excerpt: str
    provenance: str
    status: str
    version: int


class Detail(SourceInfo):
    pages: list[dict]
    items: list[ItemInfo]
    report: dict
    schema_fields: list[str]
    conflicts: list[dict]


class Edit(BaseModel):
    pointer: str = Field(pattern=r"^/.{1,512}$")
    value: str | bool | int | float | None

    @field_validator("value")
    @classmethod
    def bounded(cls, value):
        if isinstance(value, str) and len(value) > 2400:
            raise ValueError("Survey value is too long")
        return value


class Confirmation(BaseModel):
    version: int
    fields: list[Edit] = Field(min_length=1, max_length=4000)


class Reparse(BaseModel):
    kind: Kind | Literal["auto"] = "auto"


class SourceQuery(Query):
    document_type: Kind | None = None
    programme: str = Field("", max_length=120)
    course_code: str = Field("", max_length=16)
    verification: str = Field("", max_length=80)


class Trace(BaseModel):
    model_config = ConfigDict(extra="allow")
    query: str
    intent: str
    answer: str | None
    selected: list[dict]


class ReviewRow(BaseModel):
    version: int
    decision: Literal["confirm", "reject"]


class GraphStatus(BaseModel):
    state: str
    pending: int


def summary(doc):
    return {k: getattr(doc, k) for k in SourceInfo.model_fields}


def detail(s, doc):
    items = list(
        s.scalars(
            select(SourceItem)
            .where(SourceItem.document_id == doc.id)
            .order_by(SourceItem.version, SourceItem.created_at)
        )
    )
    current = [i for i in items if i.status == "active"]
    all_records = catalog(s)
    graph = [r for r in all_records if r["evidence"][0].get("document_id") == doc.id]
    conflicts = []
    for rel in ("ENROLLED_AT", "PURSUING_PROGRAMME", "BELONGS_TO_DEPARTMENT", "DOCUMENTED_CPI"):
        if any(r["relation"] == rel for r in graph):
            related = [r for r in all_records if r["relation"] == rel]
            if len({r["value"].casefold() for r in related}) > 1:
                conflicts.append(
                    {"relation": rel, "values": list(dict.fromkeys(r["value"] for r in related))}
                )
    pending = set(
        s.scalars(
            select(VectorChange.memory_id).where(VectorChange.memory_id.in_([v.id for v in current]))
        )
    )
    return summary(doc) | {
        "pages": doc.pages,
        "items": [row(i) for i in items],
        "schema_fields": list(FIELDS),
        "conflicts": conflicts,
        "report": {
            "conflicts": len(conflicts),
            "pages": len(doc.pages),
            "active": len(current),
            "review": sum(i.status == "review" for i in items),
            "course_rows": sum(
                i.relation
                in ("HAS_COMPLETED_COURSE", "HAS_CURRICULUM_COURSE", "CURRENT_COURSE", "COURSE_ATTEMPT")
                for i in current
            ),
            "graph_edges": len(graph),
            "graph_nodes": len({n for r in graph for n in ends(r)}),
            "vectors_pending": len(pending),
            "memories": len({i.memory_id for i in current if i.memory_id}),
        },
    }


def router(engine, read, write):
    r = APIRouter(prefix="/api/v1")

    @r.post("/sources/upload", status_code=202, response_model=SourceInfo)
    def upload(
        file: UploadFile = File(...),
        kind: Kind | Literal["auto"] = Form("auto"),
        s=Depends(write, scope="function"),
    ):
        return summary(receive(s, file.filename, file.file.read(16 * 1024 * 1024 + 1), kind))

    @r.get("/sources", response_model=list[SourceInfo])
    def sources(s=Depends(read)):
        return [summary(d) for d in s.scalars(select(Document).order_by(Document.created_at.desc()))]

    @r.get("/sources/{did}", response_model=Detail)
    def source(did: str, s=Depends(read)):
        return detail(s, one(s, Document, did))

    @r.get("/sources/{did}/original")
    def original(did: str, s=Depends(read)):
        d = one(s, Document, did)
        return Response(
            d.raw,
            media_type="application/pdf" if d.raw.startswith(b"%PDF") else "application/json",
            headers={"Content-Disposition": "attachment", "X-Content-Type-Options": "nosniff"},
        )

    @r.post("/sources/{did}/reprocess", response_model=SourceInfo, status_code=202)
    def reprocess(did: str, p: Reparse, s=Depends(write, scope="function")):
        d = one(s, Document, did)
        if d.status in ("queued", "processing"):
            raise HTTPException(409, "Processing already queued")
        if (
            d.kind == "survey_json"
            and p.kind not in ("survey_json", "auto")
            or d.kind != "survey_json"
            and p.kind == "survey_json"
        ):
            raise HTTPException(422, "Incompatible file type")
        if d.kind != "survey_json":
            d.requested_kind = p.kind
        d.status = "queued"
        return summary(d)

    @r.post("/sources/{did}/confirm", response_model=Detail)
    def confirm(did: str, p: Confirmation, s=Depends(write, scope="function")):
        d = one(s, Document, did)
        if d.version != p.version:
            raise HTTPException(409, "Source changed. Reload before confirming.")
        confirm_fields(s, engine, d, p.fields)
        return detail(s, d)

    @r.post("/sources/{did}/rows/{iid}/review", response_model=Detail)
    def review_row(did: str, iid: str, p: ReviewRow, s=Depends(write, scope="function")):
        from .sources import publish, retire

        d = one(s, Document, did)
        old = one(s, SourceItem, iid)
        if old.document_id != d.id or d.kind == "survey_json":
            raise HTTPException(422, "Invalid document row")
        if d.version != p.version or old.status not in ("active", "review"):
            raise HTTPException(409, "Source changed. Reload before reviewing.")
        retire(s, old)
        d.version += 1
        item = SourceItem(
            document_id=d.id,
            version=d.version,
            field=old.field,
            locator=old.locator,
            excerpt=old.excerpt,
            relation=old.relation,
            subject=old.subject,
            value=old.value,
            provenance="user_reviewed_document",
            status="active" if p.decision == "confirm" else "rejected",
        )
        s.add(item)
        if item.status == "active":
            publish(s, engine, d, item, True)
        s.flush()
        return detail(s, d)

    @r.delete("/sources/{did}", status_code=204)
    def remove(did: str):
        with engine.db.write() as s:
            d = one(s, Document, did)
            engine.forget_conversation(s, one(s, Conversation, d.journal_id))
        engine.vectors.drain(engine.db)
        return Response(status_code=204)

    @r.post("/retrieval/query", response_model=Trace)
    @r.post("/retrieval/debug", response_model=Trace)
    def query(p: SourceQuery, s=Depends(read)):
        from .cdf import intent
        from .source_inference import refine

        suggestion = (
            refine(engine.provider, p.query) if intent(p.query)[0] == "general_conversation" else None
        )
        return retrieve(s, engine, p.query, suggestion, p)

    @r.get("/graph/status", response_model=GraphStatus)
    def status(s=Depends(read)):
        return {
            "state": engine.graph.state,
            "pending": s.scalar(select(func.count()).select_from(GraphChange)),
        }

    @r.post("/graph/reindex", response_model=GraphStatus)
    def repair(s=Depends(write, scope="function")):
        existing = set(s.scalars(select(GraphChange.record)))
        for cls in (Memory, SourceItem):
            for rid in s.scalars(select(cls.id)):
                if rid not in existing:
                    s.add(GraphChange(record=rid))
        engine.graph.next_try = 0
        s.flush()
        return status(s)

    @r.get("/graph/entities/{entity}/relations", response_model=list[dict])
    def relations(entity: str, s=Depends(read)):
        records = catalog(s)
        ids = engine.graph.traverse(records, [], {entity.casefold()})
        return [v for v in records if v["id"] in ids]

    @r.get("/academic/profile", response_model=list[dict])
    def academic_profile(s=Depends(read)):
        return [
            v
            for v in catalog(s)
            if v["relation"]
            in (
                "ENROLLED_AT",
                "ACADEMIC_YEAR",
                "PURSUING_PROGRAMME",
                "BELONGS_TO_DEPARTMENT",
                "DOCUMENTED_CPI",
                "CURRENT_COURSE_STATUS",
            )
        ]

    @r.get("/academic/semesters", response_model=list[dict])
    def academic_semesters(s=Depends(read)):
        terms = {}
        for v in catalog(s):
            if v["relation"] in ("HAS_COMPLETED_COURSE", "COURSE_ATTEMPT", "DOCUMENTED_SPI") and v[
                "meta"
            ].get("semester"):
                key = (v["meta"].get("session", ""), v["meta"]["semester"])
                terms.setdefault(key, []).append(v)
        return [{"session": a, "semester": b, "records": items} for (a, b), items in terms.items()]

    @r.get("/curriculum/programmes", response_model=list[str])
    def programmes(s=Depends(read)):
        return sorted(
            {
                v["meta"]["programme"]
                for v in catalog(s)
                if v["relation"] == "HAS_CURRICULUM_COURSE" and v["meta"].get("programme")
            }
        )

    @r.get("/survey/schema", response_model=dict)
    def survey_schema():
        return {k: {"relation": v[0], "persona_field": v[1]} for k, v in FIELDS.items()}

    @r.get("/academic/courses", response_model=list[ItemInfo])
    @r.get("/curriculum/courses", response_model=list[ItemInfo])
    def courses(request: Request, programme: str = "", s=Depends(read)):
        rels = (
            ["HAS_CURRICULUM_COURSE", "HAS_REQUIREMENT", "HAS_PREREQUISITE", "EQUIVALENT_TO"]
            if "/curriculum/" in request.url.path
            else ["HAS_COMPLETED_COURSE", "CURRENT_COURSE", "COURSE_ATTEMPT", "HAS_DOCUMENTED_GRADE"]
        )
        return [
            row(i)
            for i in s.scalars(
                select(SourceItem).where(SourceItem.status == "active", SourceItem.relation.in_(rels))
            )
            if not programme or i.value.get("programme") == programme
        ]

    return r
