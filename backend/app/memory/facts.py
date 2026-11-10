from datetime import timedelta

from sqlalchemy import select

from ..contracts import FIELDS, SCALARS, ConflictDecision
from ..db import row
from ..models import Assertion, Conversation, Evidence, Message, PersonaRevision, Semantic, now
from ..vectors import changed
from .extraction import grounded, normal, stated_as, words


def sources(s, record_id):
    return [
        dict(message_id=m.id, conversation_id=m.conversation_id, timestamp=m.created_at, span=e.span)
        | (
            {
                "document_id": m.details["document_id"],
                "filename": m.details.get("filename", "Source document"),
                "location": m.details.get("locator"),
                "verification": m.details.get("provenance"),
            }
            if m.details.get("document_id")
            else {}
        )
        for e, m in s.execute(
            select(Evidence, Message)
            .join(Message, Evidence.message_id == Message.id)
            .where(Evidence.memory_id == record_id)
            .order_by(Message.created_at)
        )
    ]


def describe(s, mem):
    evidence = sources(s, mem.id)
    basis = (
        "manual"
        if mem.manual
        else "explicit"
        if mem.origin == "explicit"
        else "supported observation"
        if len(evidence) >= 3 and mem.status == "active"
        else "hypothesis"
    )
    return row(mem) | {"evidence": evidence, "basis": basis}


def link(s, mem, m, quote):
    s.flush()
    if not s.scalar(
        select(Evidence.id).where(Evidence.memory_id == mem.id, Evidence.message_id == m.id)
    ):
        s.add(Evidence(memory_id=mem.id, message_id=m.id, span=quote))
        s.flush()


def revise(s, assertion, op, reason):
    s.flush()
    s.add(
        PersonaRevision(
            assertion_id=assertion.id,
            operation=op,
            detail={
                "path": assertion.path,
                "value": assertion.value,
                "scope": assertion.scope,
                "status": assertion.status,
                "reason": reason,
            },
        )
    )


def transition(s, mem, status, at, successor=None):
    mem.status = status
    mem.valid_until = at
    mem.superseded_by = successor.id if successor else None
    if isinstance(mem, Assertion):
        revise(s, mem, "SUPERSEDE" if successor else "REMOVE", status)
    else:
        changed(s, mem, "delete")


def assertion_for(s, fact):
    return s.scalar(select(Assertion).where(Assertion.semantic_id == fact.id))


def until(path, origin, at):
    if origin == "inferred":
        return at + timedelta(days=30)
    if path == "academic_profile.reported_difficulties" or path.startswith(
        ("goals.short", "constraints.time")
    ):
        return at + timedelta(days=90)
    if path in ("identity.academic_year", "academic_profile.current_courses"):
        return at + timedelta(days=365)
    return None


def equivalent(a, b, vectors):
    a, b = normal(a), normal(b)
    if a == b:
        return True
    opposing = {"no", "not", "never", "short", "long", "brief", "detailed", "before", "after", "without"}
    if (words(a) ^ words(b)) & opposing or {v for v in words(a) if v.isdigit()} != {
        v for v in words(b) if v.isdigit()
    }:
        return False
    shared = words(a) & words(b)
    return len(shared) / max(len(words(a) | words(b)), 1) >= 0.8 and vectors.similarity(a, b) >= 0.92


def resolve(conflicts, manual, correction, origin, at):
    if origin == "inferred":
        return ConflictDecision(status="pending", reason="inference requires evidence or review")
    if conflicts and not (
        manual or correction and all(not f.manual and f.observed_at <= at for f in conflicts)
    ):
        return ConflictDecision(status="pending", reason="conflicting values require learner review")
    return ConflictDecision(
        status="active", reason="manual edit" if manual else "grounded learner statement"
    )


def accept(s, proposal, m, vectors, manual=False, target=None, source_verified=False):
    if not manual and not source_verified and not grounded(proposal, m):
        return None
    path, scope, val = proposal.path, normal(proposal.scope), proposal.value
    origin = proposal.origin
    if (
        not manual
        and not source_verified
        and origin == "explicit"
        and not stated_as(path, proposal.quote)
    ):
        origin = "inferred"
    if origin == "inferred" and not path.startswith(("learning_preferences.", "behavioral_patterns.")):
        return None
    entries = list(
        s.scalars(
            select(Semantic)
            .where(Semantic.predicate == path, Semantic.scope == scope)
            .order_by(Semantic.observed_at.desc())
        )
    )
    # A replay belongs to the version that originally cited this source, even after a later reversal.
    if not manual:
        for old in entries:
            if normal(old.value) == normal(val) and s.scalar(
                select(Evidence.id).where(Evidence.memory_id == old.id, Evidence.message_id == m.id)
            ):
                return assertion_for(s, old) if old.status in ("active", "pending") else None
    for old in entries:
        if equivalent(old.value, val, vectors):
            if old.status in ("rejected", "superseded", "archived"):
                restatement = (
                    old.status == "superseded"
                    and proposal.correction
                    and proposal.origin == "explicit"
                    and old.valid_until
                    and m.created_at >= old.valid_until
                )
                if not manual and not restatement:
                    return None
                continue
            a = assertion_for(s, old)
            link(s, old, m, proposal.quote)
            link(s, a, m, proposal.quote)
            old.last_confirmed_at = max(old.last_confirmed_at, m.created_at)
            refs = sources(s, old.id)
            if old.status == "pending" and origin == "explicit" and not manual:
                conflicts = [
                    f
                    for f in entries
                    if f.status == "active"
                    and path in SCALARS
                    and (not f.valid_until or f.valid_until > m.created_at)
                ]
                decision = resolve(conflicts, False, proposal.correction, origin, m.created_at)
                old.origin = a.origin = "explicit"
                old.confidence = a.confidence = max(old.confidence, proposal.confidence)
                if decision.status == "active":
                    old.status = a.status = "active"
                    for f in conflicts:
                        transition(s, f, "superseded", m.created_at, old)
                        transition(s, assertion_for(s, f), "superseded", m.created_at, a)
                    revise(s, a, "REPLACE", "confirmed by explicit learner statement")
                    changed(s, old)
            if (
                old.status == "pending"
                and old.origin == "inferred"
                and path.startswith("behavioral_patterns.")
                and len(refs) >= 3
                and len({r["conversation_id"] for r in refs}) >= 2
            ):
                old.status = a.status = "active"
                old.confidence = a.confidence = max(0.78, old.confidence)
                revise(s, a, "REPLACE", "repeated observation across sessions")
                changed(s, old)
            if old.status == "active":
                old.valid_until = a.valid_until = until(path, old.origin, old.last_confirmed_at)
            if manual:
                old.manual = a.manual = True
                if old.status == "pending":
                    decide(s, a, True)
                if target and target.id != old.id and target.status == "active":
                    transition(s, target, "superseded", m.created_at, old)
                    transition(s, assertion_for(s, target), "superseded", m.created_at, a)
            return a

    active = [
        v
        for v in entries
        if v.status == "active" and (not v.valid_until or v.valid_until > m.created_at)
    ]
    conflicts = ([target] if target else active) if path in SCALARS or target else []
    decision = resolve(conflicts, manual, proposal.correction, origin, m.created_at)
    status = decision.status
    at = m.created_at
    content = f"{path.split('.')[-1].replace('_', ' ')}: {val}" + (f" (for {scope})" if scope else "")
    common = dict(
        content=content,
        origin=origin,
        confidence=proposal.confidence,
        status=status,
        valid_from=at,
        valid_until=until(path, origin, at),
        manual=manual,
        synthetic=s.get(Conversation, m.conversation_id).synthetic,
    )
    fact = Semantic(
        predicate=path,
        value=val,
        scope=scope,
        category=path.split(".")[0],
        observed_at=at,
        last_confirmed_at=at,
        **common,
    )
    s.add(fact)
    s.flush()
    a = Assertion(path=path, scope=scope, value=val, semantic_id=fact.id, **common)
    s.add(a)
    link(s, fact, m, proposal.quote)
    link(s, a, m, proposal.quote)
    revise(s, a, "REPLACE" if conflicts and status == "active" else "ADD", decision.reason)
    if status == "active":
        for old in conflicts:
            transition(s, old, "superseded", at, fact)
            transition(s, assertion_for(s, old), "superseded", at, a)
        changed(s, fact)
    return a


def decide(s, a, confirm):
    fact = s.get(Semantic, a.semantic_id)
    if confirm:
        if a.path in SCALARS:
            for other in s.scalars(
                select(Assertion).where(
                    Assertion.path == a.path,
                    Assertion.scope == a.scope,
                    Assertion.status == "active",
                    Assertion.id != a.id,
                )
            ):
                transition(s, other, "superseded", now(), a)
                transition(s, s.get(Semantic, other.semantic_id), "superseded", now(), fact)
        a.status = fact.status = "active"
        a.valid_until = fact.valid_until = None
        a.superseded_by = fact.superseded_by = None
        a.manual = fact.manual = True
        revise(s, a, "REPLACE", "confirmed by learner")
        changed(s, fact)
    else:
        transition(s, a, "rejected", now())
        transition(s, fact, "rejected", now())
    return a


def profile(s):
    assertions = list(s.scalars(select(Assertion).order_by(Assertion.created_at)))
    tree = {
        group: {k: None if f"{group}.{k}" in SCALARS else [] for k in keys}
        for group, keys in FIELDS.items()
    }
    for a in assertions:
        if a.status != "active" or a.valid_until and a.valid_until <= now():
            continue
        sec, key = a.path.split(".")
        if a.path in SCALARS:
            if not a.scope:
                tree[sec][key] = a.value
        else:
            tree[sec][key].append(a.value)
    return {"profile": tree, "assertions": [describe(s, a) for a in assertions]}
