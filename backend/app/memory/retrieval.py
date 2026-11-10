import re
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from ..db import settings
from ..models import Conversation, Episode, Evidence, Memory, now
from .extraction import words
from .facts import sources
from .working import get_recent_context, tokens

STOP = set(
    "i my me we the a an what was were did do does with in of to last this week have about you remember give show all at from for which please and is am how can it our that".split()
)
ALIASES = {
    "struggle": "difficulty",
    "struggled": "difficulty",
    "struggling": "difficulty",
    "difficulties": "difficulty",
    "trouble": "difficulty",
    "preference": "prefer",
    "preferences": "prefer",
    "preferred": "prefer",
    "explanations": "explanation",
    "strengths": "strength",
    "goals": "goal",
}


def terms(value):
    return {ALIASES.get(x, x) for x in words(value) - STOP}


def inspect(s, query, thread, cfg, vectors, at=None):
    at = at or now()
    prefs = settings(s)
    budget = min(query.budget or prefs["max_tokens"], prefs["max_tokens"])
    q = query.query.lower()
    today = at.astimezone(ZoneInfo(prefs["timezone"])).date()
    start, end = query.start, query.end
    if "last week" in q and not start and not end:
        end = today - timedelta(days=today.weekday() + 1)
        start = end - timedelta(days=6)
    qwords = terms(q)
    matches = set()
    if qwords:
        expression = " OR ".join('"' + w + '"' for w in sorted(qwords)[:30])
        matches = set(
            s.scalars(
                text(
                    "SELECT id FROM memory_search WHERE memory_search MATCH :query ORDER BY bm25(memory_search) LIMIT 150"
                ),
                {"query": expression},
            )
        )
    vector_scores = vectors.search(q)
    candidates = []
    excluded = []
    immediate = bool(
        re.search(
            r"\b(?:equation|just|we were|discussing|last message|this conversation|earlier in this)\b", q
        )
    )
    last_thread = None
    if "last" in q and "conversation" in q:
        focus = qwords - {
            "conversation",
            "difficulty",
            "topic",
            "topics",
            "discuss",
            "discussed",
            "understand",
        }
        for episode, title in s.execute(
            select(Episode, Conversation.title)
            .join(Conversation, Episode.conversation_id == Conversation.id)
            .where(Episode.start_time <= at, Episode.status == "active")
            .order_by(Episode.end_time.desc())
        ):
            if not focus or focus & terms(title + " " + episode.content):
                last_thread = episode.conversation_id
                break
    if thread and query.layer in (None, "working"):
        from ..knowledge import question

        for i, m in enumerate(reversed(get_recent_context(s, thread, at))):
            if m.role == "user" and question(m.content) and "just ask" not in q:
                continue
            if m.content == query.query or start or end or last_thread and thread.id != last_thread:
                continue
            cited = [h["id"] for h in m.details.get("sources", []) if h["layer"] != "working"]
            supported = list(
                s.scalars(
                    select(Memory)
                    .join(Evidence, Memory.id == Evidence.memory_id)
                    .where(Evidence.message_id == m.id, Memory.layer.in_(["semantic", "persona"]))
                )
            )
            if (
                cited
                and any(
                    (record := s.get(Memory, key)) is None
                    or record.status != "active"
                    or record.valid_until
                    and record.valid_until <= at
                    for key in cited
                )
                or supported
                and all(
                    record.status != "active" or record.valid_until and record.valid_until <= at
                    for record in supported
                )
            ):
                excluded.append({"id": m.id, "reason": "source was corrected or rejected"})
                continue
            score = (
                (1.3 if immediate else 0.48)
                + 0.26 * len(terms(m.content) & qwords) / max(1, len(qwords))
                - 0.012 * i
            )
            candidates.append(
                dict(
                    id=m.id,
                    layer="working",
                    content=m.content,
                    score=round(score, 4),
                    reasons=["recent turn", m.role],
                    evidence=[dict(message_id=m.id, conversation_id=thread.id, timestamp=m.created_at)],
                    timestamp=m.created_at,
                )
            )
    # SQL prefilters expensive long-term candidates; FTS and vector matches can recall older records.
    stmt = select(Memory).where(Memory.user_id == thread.user_id) if thread else select(Memory)
    if query.layer and query.layer != "working":
        stmt = stmt.where(Memory.layer == query.layer)
    if query.layer != "working":
        hit_ids = matches | set(vector_scores)
        selected = list(s.scalars(stmt.where(Memory.id.in_(hit_ids)).limit(220))) if hit_ids else []
        seen = {m.id for m in selected}
        for m in s.scalars(stmt.order_by(Memory.updated_at.desc()).limit(180)):
            if m.id not in seen:
                selected.append(m)
        for mem in selected:
            reason = None
            when = mem.start_time if isinstance(mem, Episode) else mem.valid_from
            local_day = when.astimezone(ZoneInfo(prefs["timezone"])).date()
            if mem.status != "active":
                reason = mem.status
            elif mem.valid_until and mem.valid_until <= at or mem.valid_from > at:
                reason = "outside validity"
            elif start and local_day < start or end and local_day > end:
                reason = "outside date range"
            elif last_thread and (not isinstance(mem, Episode) or mem.conversation_id != last_thread):
                reason = "outside last matching conversation"
            if reason:
                excluded.append({"id": mem.id, "reason": reason})
                continue
            mwords = terms(mem.content)
            if isinstance(mem, Episode):
                mwords.add(mem.event_type)
            lexical = len(mwords & qwords) / max(1, len(qwords))
            if mem.id in matches:
                lexical = max(0.32, lexical)
            if (
                "prefer" in qwords
                and mem.layer == "persona"
                and mem.path.startswith("learning_preferences.")
            ):
                lexical = max(0.83, lexical)
            elif "strength" in qwords and "reported_strengths" in getattr(mem, "path", ""):
                lexical = max(0.8, lexical)
            elif "goal" in qwords and getattr(mem, "path", "").startswith("goals."):
                lexical = max(0.8, lexical)
            elif mem.layer == "persona" and qwords & {"know", "profile", "persona"}:
                lexical = max(0.64, lexical)
            # Active style preferences can guide tutoring even without an explicit preference query.
            personal = (
                mem.layer == "persona"
                and mem.path.startswith("learning_preferences.")
                and (not mem.scope or bool(terms(mem.scope) & qwords))
            )
            if personal and not start and not end and not immediate:
                lexical = max(0.24, lexical)
            sim = vector_scores.get(mem.id, 0.0)
            if lexical == 0 and sim < 0.42:
                excluded.append({"id": mem.id, "reason": "low relevance"})
                continue
            age = max(0, (at - when).days)
            parts = {
                "lexical": lexical,
                "vector": sim,
                "recency": 1 / (1 + age / 14) if isinstance(mem, Episode) else 0,
                "importance": mem.importance,
                "explicit": float(mem.manual or mem.origin == "explicit"),
                "confidence": mem.confidence,
            }
            score = sum(parts[k] * cfg.ranking[k] for k in parts)
            if isinstance(mem, Episode) and (
                start or "when" in q or "conversation" in q or "difficulty" in qwords
            ):
                score += 0.24
            if mem.layer == "persona" and ("prefer" in qwords or personal):
                score += 0.09
            refs = sources(s, mem.id)
            candidates.append(
                dict(
                    id=mem.id,
                    layer=mem.layer,
                    content=mem.content,
                    score=round(score, 4),
                    reasons=[f"{k} {v:.2f}" for k, v in parts.items() if v],
                    evidence=refs,
                    timestamp=when,
                )
            )
    picked, used, seen_content, seen_provenance = [], 0, set(), {}
    for hit in sorted(candidates, key=lambda x: (x["score"], x["timestamp"]), reverse=True):
        normalized = hit["content"].casefold()
        evidence_key = frozenset(e["message_id"] for e in hit["evidence"])
        previous_layers = seen_provenance.get(evidence_key, set())
        if (
            normalized in seen_content
            or previous_layers
            and ("working" in previous_layers or hit["layer"] == "working")
        ):
            excluded.append({"id": hit["id"], "reason": "duplicate content and evidence"})
            continue
        # Count the serialized context handed to the provider, including IDs and source links.
        import json

        cost = tokens(json.dumps(hit, default=str, ensure_ascii=False))
        if used + cost > budget:
            excluded.append({"id": hit["id"], "reason": "context budget"})
            continue
        used += cost
        picked.append(hit)
        seen_content.add(normalized)
        if evidence_key:
            seen_provenance.setdefault(evidence_key, set()).add(hit["layer"])
    return {
        "query": query.query,
        "selected": picked,
        "excluded": excluded[:120],
        "tokens": used,
        "budget": budget,
    }
