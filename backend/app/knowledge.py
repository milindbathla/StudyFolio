"""Evidence projection and allowlisted local graph adapter. SQLite determines which edges are current."""

import os
import re
import time
from urllib.parse import urlparse

from sqlalchemy import select

from .config import USER
from .memory.facts import sources
from .models import Episode, Memory, Message, Semantic, now
from .source_models import Document, GraphChange, SourceItem
from .source_parse import mapping

RELATIONS = {
    "ENROLLED_AT": "Institution",
    "PURSUING_PROGRAMME": "Programme",
    "BELONGS_TO_DEPARTMENT": "Department",
    "LEARNER_NAME": "Name",
    "ACADEMIC_YEAR": "Semester",
    "CURRENT_SEMESTER": "Semester",
    "DOCUMENTED_CPI": "AcademicPerformance",
    "DOCUMENTED_SPI": "AcademicPerformance",
    "CURRENT_COURSE_STATUS": "AcademicRecord",
    "CURRENT_COURSE": "Course",
    "HAS_COMPLETED_COURSE": "Course",
    "COURSE_ATTEMPT": "Course",
    "HAS_DOCUMENTED_GRADE": "Grade",
    "HAS_CURRICULUM_COURSE": "Course",
    "HAS_PREREQUISITE": "Course",
    "EQUIVALENT_TO": "Course",
    "HAS_REQUIREMENT": "Requirement",
    "HAS_REPORTED_SKILL_LEVEL": "Skill",
    "HAS_GOAL": "Goal",
    "HAS_PREFERENCE": "Preference",
    "INTERESTED_IN": "Interest",
    "HAS_CONSTRAINT": "Constraint",
    "DISCUSSED_TOPIC": "Topic",
    "EXPERIENCED_DIFFICULTY_WITH": "Topic",
    "PASSAGE": "Document",
    "SURVEY_FIELD": "SurveyField",
}


def canonical(rel, value):
    text = " ".join(str(value).split())
    if rel == "ENROLLED_AT" and re.fullmatch(
        r"(?:iit\s*k(?:anpur)?|indian institute of technology[ ,]+kanpur)", text, re.I
    ):
        return "IIT Kanpur"
    if rel == "PURSUING_PROGRAMME" and re.fullmatch(
        r"B\.?\s*Tech\.?|BT|Bachelor of Technology", text, re.I
    ):
        return "B.Tech"
    if rel == "BELONGS_TO_DEPARTMENT" and re.fullmatch(
        r"ME|Mech(?:anical)?\.?\s+Eng(?:ineering|g\.?)", text, re.I
    ):
        return "Mechanical Engineering"
    return text


def question(text):
    return text.strip().endswith("?") or bool(
        re.match(r"^(?:where|which|what|when|why|how|do i|am i|in which)\b", text.strip(), re.I)
    )


def record(s, obj):
    if not obj or obj.status != "active":
        return None
    if isinstance(obj, SourceItem):
        if obj.relation not in RELATIONS:
            return None
        doc = s.get(Document, obj.document_id)
        if not doc or not doc.version:
            return None
        mem = s.get(Memory, obj.memory_id) if obj.memory_id else None
        if (
            mem
            and mem.status not in ("active", "pending")
            or mem
            and mem.valid_until
            and mem.valid_until <= now()
        ):
            return None
        raw = obj.value["raw"]
        val = (
            obj.field.removeprefix("goal_").replace("_", " ")
            if raw is True and obj.relation == "HAS_GOAL"
            else raw
        )
        r = obj.relation
        cite = {
            "document_id": doc.id,
            "filename": doc.filename,
            "location": obj.locator,
            "source_type": doc.kind,
            "verification": obj.provenance,
            "message_id": obj.message_id,
            "conversation_id": doc.journal_id,
            "timestamp": obj.created_at.isoformat(),
            "span": obj.excerpt,
        }
        subject = obj.subject if obj.subject != "Document" else "Document:" + doc.id
        authority = 2
        if obj.provenance == "user_corrected":
            authority = 4
        elif doc.kind == "academic_transcript" and r in (
            "DOCUMENTED_CPI",
            "DOCUMENTED_SPI",
            "HAS_DOCUMENTED_GRADE",
            "HAS_COMPLETED_COURSE",
        ):
            authority = 3
        elif obj.provenance.startswith("user_") and r not in (
            "DOCUMENTED_CPI",
            "DOCUMENTED_SPI",
            "HAS_DOCUMENTED_GRADE",
        ):
            authority = 3
        return dict(
            id=obj.id,
            relation=r,
            subject=subject,
            value=canonical(r, val),
            field=obj.field,
            meta=obj.value,
            evidence=[cite],
            authority=authority,
        )
    if obj.valid_until and obj.valid_until <= now() or obj.valid_from > now() or obj.synthetic:
        return None
    if isinstance(obj, Semantic):
        path = obj.predicate
        rel = next(
            (
                mapping(k)[0]
                for k in (
                    "institution",
                    "programme",
                    "department",
                    "name",
                    "year_of_study",
                    "completed_courses",
                    "current_courses",
                )
                if mapping(k)[1] == path
            ),
            None,
        )
        rel = rel or (
            "HAS_GOAL"
            if path.startswith("goals.")
            else "HAS_PREFERENCE"
            if path.startswith("learning_preferences.")
            else "INTERESTED_IN"
            if path.startswith("interests.")
            else "SURVEY_FIELD"
        )
        val = obj.value
    elif isinstance(obj, Episode):
        rel = "EXPERIENCED_DIFFICULTY_WITH" if obj.event_type == "difficulty" else "DISCUSSED_TOPIC"
        val = obj.content
        path = "episode"
    else:
        return None
    evidence = []
    for ref in sources(s, obj.id):
        m = s.get(Message, ref["message_id"])
        if m and m.role == "user" and not m.details.get("document_id") and not question(m.content):
            evidence.append(
                ref
                | {
                    "timestamp": ref["timestamp"].isoformat(),
                    "source_type": "conversation",
                    "verification": "learner_confirmed" if obj.manual else obj.origin,
                }
            )
    if not evidence:
        return None
    return dict(
        id=obj.id,
        relation=rel,
        subject="Learner",
        value=canonical(rel, val),
        field=path,
        meta={"scope": getattr(obj, "scope", "")},
        evidence=evidence,
        authority=4 if obj.manual else 2,
    )


def catalog(s):
    records = []
    for cls in (SourceItem, Semantic, Episode):
        for obj in s.scalars(select(cls).where(cls.status == "active")):
            if r := record(s, obj):
                records.append(r)
    return records


def ends(r):
    return r["subject"].casefold(), (RELATIONS[r["relation"]] + ":" + r["value"]).casefold()


class LocalGraph:
    def __init__(self, namespace):
        import hashlib

        self.owner = hashlib.sha256((namespace + USER).encode()).hexdigest()
        self.driver = None
        self.state = "SQLite graph · Neo4j unconfigured"
        self.next_try = 0.0

    def connect(self):
        if not os.getenv("NEO4J_PASSWORD") or time.monotonic() < self.next_try:
            return False
        if self.driver:
            return True
        uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
        if (
            urlparse(uri).hostname not in ("localhost", "127.0.0.1", "::1")
            or urlparse(uri).scheme != "bolt"
        ):
            self.state = "SQLite graph · local bolt URI required"
            return False
        try:
            from neo4j import GraphDatabase

            self.driver = GraphDatabase.driver(
                uri,
                auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD")),
                connection_timeout=2,
                connection_acquisition_timeout=3,
                max_transaction_retry_time=0,
            )
            self.driver.verify_connectivity()
            self.state = "Neo4j connected"
            return True
        except Exception:
            self.failed()
            return False

    def failed(self):
        if self.driver:
            self.driver.close()
        self.driver = None
        self.next_try = time.monotonic() + 30
        self.state = "SQLite graph · Neo4j unavailable"

    def sync(self, db):
        if not self.connect():
            return
        with db.sessions() as s:
            changes = list(s.scalars(select(GraphChange).order_by(GraphChange.created_at).limit(128)))
            payload = []
            context = []
            for ch in changes:
                r = record(s, s.get(SourceItem, ch.record) or s.get(Memory, ch.record))
                if r:
                    left, right = ends(r)
                    anchor = "assertion:" + r["id"]

                    def extra(a, b, kind, atype, btype, record_id=r["id"]):
                        context.append(
                            {
                                "id": record_id,
                                "a": a,
                                "b": b,
                                "rel": kind,
                                "atype": atype,
                                "btype": btype,
                            }
                        )

                    extra(anchor, right, "ASSERTS", "Assertion", RELATIONS[r["relation"]])
                    for e in r["evidence"]:
                        msg = "message:" + e["message_id"]
                        extra(anchor, msg, "SUPPORTED_BY", "Assertion", "Message")
                        extra(
                            msg,
                            "conversation:" + e["conversation_id"],
                            "IN_CONVERSATION",
                            "Message",
                            "Conversation",
                        )
                        if e.get("document_id"):
                            extra(
                                msg,
                                "document:" + e["document_id"],
                                "EXTRACTED_FROM",
                                "Message",
                                "CurriculumTemplate"
                                if e["source_type"] == "curriculum_template"
                                else "Document",
                            )
                    if r["meta"].get("semester"):
                        extra(
                            anchor,
                            "semester:"
                            + str(r["meta"].get("session", ""))
                            + ":"
                            + str(r["meta"]["semester"]),
                            "HAS_SEMESTER",
                            "Assertion",
                            "Semester",
                        )
                    if r["relation"] == "HAS_DOCUMENTED_GRADE":
                        extra(
                            left,
                            "course:" + r["meta"]["course"].lower(),
                            "ATTEMPTED_COURSE",
                            "AcademicRecord",
                            "Course",
                        )
                    payload.append(
                        {
                            "id": r["id"],
                            "left": left,
                            "right": right,
                            "rel": r["relation"],
                            "kind": RELATIONS[r["relation"]],
                            "evidence": [v["message_id"] for v in r["evidence"] if v.get("message_id")],
                        }
                    )
        if not changes:
            return
        try:
            with self.driver.session() as session:

                def update(tx):
                    tx.run(
                        "MATCH (:SFEntity {owner:$u})-[e:SF_REL]->() WHERE e.id IN $ids DELETE e",
                        u=self.owner,
                        ids=[c.record for c in changes],
                    ).consume()
                    tx.run(
                        "UNWIND $rows AS r MERGE (a:SFEntity {owner:$u,key:r.left}) MERGE (b:SFEntity {owner:$u,key:r.right}) SET b.kind=r.kind MERGE (a)-[e:SF_REL {id:r.id}]->(b) SET e.kind=r.rel,e.evidence=r.evidence",
                        u=self.owner,
                        rows=payload,
                    ).consume()
                    tx.run(
                        "MATCH (:SFEntity {owner:$u})-[e:SF_META]->() WHERE e.id IN $ids DELETE e",
                        u=self.owner,
                        ids=[c.record for c in changes],
                    ).consume()
                    tx.run(
                        "UNWIND $rows AS r MERGE (a:SFEntity {owner:$u,key:r.a}) MERGE (b:SFEntity {owner:$u,key:r.b}) SET a.kind=r.atype,b.kind=r.btype MERGE (a)-[e:SF_META {id:r.id,kind:r.rel}]->(b)",
                        u=self.owner,
                        rows=context,
                    ).consume()
                    tx.run(
                        "MATCH (a:SFEntity {owner:$u}) WHERE NOT (a)--() DELETE a", u=self.owner
                    ).consume()

                session.execute_write(update)
            with db.write() as s:
                for old in changes:
                    if current := s.get(GraphChange, old.id):
                        s.delete(current)
        except Exception:
            self.failed()

    def traverse(self, records, rel, seeds=None):
        allowed = {r["id"] for r in records}
        if self.driver:
            try:
                with self.driver.session() as sess:
                    query = (
                        "MATCH (a:SFEntity {owner:$u})-[e:SF_REL]-(b:SFEntity {owner:$u}) WHERE a.key IN $seeds"
                        if seeds
                        else "MATCH (:SFEntity {owner:$u})-[e:SF_REL]->(:SFEntity {owner:$u}) WHERE e.kind IN $rel"
                    )
                    return [
                        v["id"]
                        for v in sess.run(
                            query + " RETURN DISTINCT e.id AS id ORDER BY id LIMIT 80",
                            u=self.owner,
                            seeds=list(seeds or []),
                            rel=rel,
                        )
                        if v["id"] in allowed
                    ]
            except Exception:
                self.failed()
        return [
            r["id"] for r in records if (bool(set(ends(r)) & seeds) if seeds else r["relation"] in rel)
        ][:80]
