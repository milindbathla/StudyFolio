"""Add private source records, reviewable evidence and durable graph reconciliation."""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = depends_on = None


def owned():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    ]


def upgrade():
    op.create_table(
        "source_documents",
        *owned(),
        sa.Column("filename", sa.String(), nullable=False),
        sa.Column("digest", sa.String(), nullable=False),
        sa.Column("raw", sa.LargeBinary(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("pages", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column(
            "journal_id",
            sa.String(36),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.UniqueConstraint("user_id", "digest"),
    )
    op.create_table(
        "source_items",
        *owned(),
        sa.Column(
            "document_id",
            sa.String(36),
            sa.ForeignKey("source_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        *[
            sa.Column(c, sa.String(), nullable=False)
            for c in ("locator", "field", "relation", "subject", "excerpt", "provenance", "status")
        ],
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("message_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        sa.Column("memory_id", sa.String(36), sa.ForeignKey("memories.id", ondelete="SET NULL")),
    )
    op.create_index("ix_source_lookup", "source_items", ["user_id", "relation", "status"])
    op.create_index("ix_source_document", "source_items", ["document_id", "version"])
    op.create_table(
        "graph_changes", *owned(), sa.Column("record", sa.String(), nullable=False, unique=True)
    )
    for table in ("source_items", "memories"):
        for action, ref in (("insert", "new"), ("update", "new"), ("delete", "old")):
            sql = f"DELETE FROM graph_changes WHERE record={ref}.id; INSERT INTO graph_changes(id,user_id,created_at,record) VALUES(lower(hex(randomblob(16))),{ref}.user_id,CURRENT_TIMESTAMP,{ref}.id);"
            if table == "source_items":
                mode = (
                    "'delete'"
                    if action == "delete"
                    else "CASE WHEN new.status='active' THEN 'upsert' ELSE 'delete' END"
                )
                sql += f" DELETE FROM vector_changes WHERE memory_id={ref}.id; INSERT INTO vector_changes(id,created_at,memory_id,layer,action) VALUES(lower(hex(randomblob(16))),CURRENT_TIMESTAMP,{ref}.id,'document_chunks',{mode});"
            op.execute(f"CREATE TRIGGER sf_{table}_{action} AFTER {action} ON {table} BEGIN {sql} END")
    op.execute(
        "INSERT INTO graph_changes(id,user_id,created_at,record) SELECT lower(hex(randomblob(16))),user_id,CURRENT_TIMESTAMP,id FROM memories WHERE status='active'"
    )


def downgrade():
    for table in ("source_items", "memories"):
        for action in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER sf_{table}_{action}")
    op.execute("DELETE FROM vector_changes WHERE layer='document_chunks'")
    for table in ("graph_changes", "source_items", "source_documents"):
        op.drop_table(table)
