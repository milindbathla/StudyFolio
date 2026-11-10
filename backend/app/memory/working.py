from datetime import timedelta

from fastapi.encoders import jsonable_encoder
from sqlalchemy import func, select

from ..db import settings
from ..models import Message, now


def tokens(text):
    # Conservative approximation for English and non-ASCII text, including short strings.
    return (len(text.encode("utf-8")) + 2) // 3


def add_message(s, thread, role, content, at=None, key=None, details=None):
    at = at or now()
    m = Message(
        conversation_id=thread.id,
        position=1
        + (
            s.scalar(select(func.max(Message.position)).where(Message.conversation_id == thread.id)) or 0
        ),
        role=role,
        content=content,
        created_at=at,
        request_key=key,
        details=jsonable_encoder(
            {"synthetic": thread.synthetic, "timezone": settings(s)["timezone"], **(details or {})}
        ),
    )
    thread.updated_at = max(thread.updated_at, at)
    s.add(m)
    s.flush()
    return m


def get_conversation_context(s, thread):
    return list(
        s.scalars(
            select(Message)
            .where(Message.conversation_id == thread.id)
            .order_by(Message.created_at, Message.position)
        )
    )


def get_recent_context(s, thread, at=None):
    cfg = settings(s)
    at = at or now()
    cutoff = max(
        at - timedelta(hours=cfg["window_hours"]),
        thread.cleared_at or at - timedelta(hours=cfg["window_hours"]),
    )
    messages = s.scalars(
        select(Message)
        .where(
            Message.conversation_id == thread.id, Message.created_at > cutoff, Message.created_at <= at
        )
        .order_by(Message.created_at.desc(), Message.position.desc())
        .limit(cfg["max_messages"])
    )
    used = 0
    result = []
    for m in messages:
        size = tokens(m.content)
        if used + size > cfg["max_tokens"]:
            break
        used += size
        result.append(m)
    return list(reversed(result))


def compact_context(s, thread):
    recent = get_recent_context(s, thread)
    before = recent[0].created_at if recent else now()
    older_than = Message.created_at < before
    if recent:
        older_than |= (Message.created_at == before) & (Message.position < recent[0].position)
    stmt = select(Message).where(Message.conversation_id == thread.id, older_than)
    if thread.cleared_at:
        stmt = stmt.where(Message.created_at > thread.cleared_at)
    older = list(s.scalars(stmt.order_by(Message.created_at.desc(), Message.position.desc()).limit(4)))
    return [{"role": m.role, "id": m.id, "excerpt": m.content[:160]} for m in reversed(older)]


def clear_working_context(thread):
    thread.cleared_at = now()


def restore_after_restart(s, thread):
    return get_recent_context(s, thread)
