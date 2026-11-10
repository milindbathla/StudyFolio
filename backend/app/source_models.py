from sqlalchemy import ForeignKey, LargeBinary, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base, Owned


class Document(Owned, Base):
    __tablename__ = "source_documents"
    filename: Mapped[str]
    digest: Mapped[str]
    raw: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    kind: Mapped[str]
    requested_kind: Mapped[str|None]
    status: Mapped[str] = mapped_column(default="queued")
    version: Mapped[int] = mapped_column(default=0)
    pages: Mapped[list] = mapped_column(default=list)
    warnings: Mapped[list] = mapped_column(default=list)
    journal_id: Mapped[str] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    __table_args__ = (UniqueConstraint("user_id", "digest"),)


class SourceItem(Owned, Base):
    __tablename__ = "source_items"
    document_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int]
    locator: Mapped[str]
    field: Mapped[str]
    value: Mapped[dict]
    relation: Mapped[str]
    subject: Mapped[str]
    excerpt: Mapped[str]
    provenance: Mapped[str]
    status: Mapped[str]
    message_id: Mapped[str | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"))
    memory_id: Mapped[str | None] = mapped_column(ForeignKey("memories.id", ondelete="SET NULL"))


class GraphChange(Owned, Base):
    __tablename__ = "graph_changes"
    record: Mapped[str] = mapped_column(unique=True)
