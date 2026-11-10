"""Preserve source order when several turns have the same timestamp."""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("messages", sa.Column("position", sa.Integer(), nullable=False, server_default="0"))
    op.execute("""
        WITH ordered AS (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY conversation_id ORDER BY created_at, rowid
            ) AS position FROM messages
        )
        UPDATE messages SET position = (SELECT position FROM ordered WHERE ordered.id = messages.id)
    """)
    op.create_index("uq_message_position", "messages", ["conversation_id", "position"], unique=True)
    op.add_column(
        "conversations",
        sa.Column("reflected_position", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    op.drop_column("conversations", "reflected_position")
    op.drop_index("uq_message_position", table_name="messages")
    op.drop_column("messages", "position")
