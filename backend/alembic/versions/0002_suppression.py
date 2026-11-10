"""Remember explicit forget decisions without retaining private values."""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "suppressed_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column(
            "message_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("fingerprint", sa.String(), nullable=False),
        sa.UniqueConstraint("message_id", "fingerprint"),
    )
    op.create_index("ix_suppressed_evidence_message_id", "suppressed_evidence", ["message_id"])


def downgrade():
    op.drop_table("suppressed_evidence")
