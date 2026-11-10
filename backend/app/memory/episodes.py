from datetime import timedelta

from sqlalchemy import select

from ..models import Conversation, Episode, Evidence
from ..vectors import changed
from .extraction import words
from .facts import link


def form(s, m, p, from_model=False):
    if p.message_id != m.id or p.quote not in m.content or not words(p.topic) <= words(m.content):
        return
    existing = s.scalar(
        select(Episode)
        .join(Evidence, Episode.id == Evidence.memory_id)
        .where(Evidence.message_id == m.id)
    )
    safe_summary = words(p.summary) <= words(p.quote) | {
        "the",
        "learner",
        "reported",
        "difficulty",
        "with",
        "studying",
        "a",
        "topic",
        "practiced",
    }
    summary = p.summary if from_model and safe_summary else p.quote
    if existing:
        if (
            from_model
            and safe_summary
            and len(list(s.scalars(select(Evidence.id).where(Evidence.memory_id == existing.id)))) == 1
        ):
            existing.content = f"Learner reported: {summary}"
            existing.details = existing.details | {"summary_method": "validated model excerpt"}
            changed(s, existing)
        return
    at = m.created_at - timedelta(days=1) if "yesterday" in m.content.lower() else m.created_at
    last = s.scalar(
        select(Episode)
        .where(
            Episode.conversation_id == m.conversation_id,
            Episode.event_type == p.kind,
            Episode.end_time.between(at - timedelta(minutes=45), at + timedelta(minutes=45)),
        )
        .order_by(Episode.end_time.desc())
    )
    if last and any(words(t) & words(p.topic) for t in last.topics):
        last.start_time, last.end_time = min(last.start_time, at), max(last.end_time, at)
        last.topics = list(dict.fromkeys([*last.topics, p.topic]))
        if p.quote not in last.content:
            last.content = (last.content + " · " + p.quote)[:1800]
        episode = last
    else:
        episode = Episode(
            conversation_id=m.conversation_id,
            content=f"Learner reported: {summary}",
            event_type=p.kind,
            topics=[p.topic],
            confidence=0.9,
            importance=0.78,
            start_time=at,
            end_time=at,
            valid_from=at,
            synthetic=s.get(Conversation, m.conversation_id).synthetic,
            details={"segmentation": "topic and 45-minute gap", "assessment": "self-report"},
        )
        s.add(episode)
    link(s, episode, m, p.quote)
    changed(s, episode)
