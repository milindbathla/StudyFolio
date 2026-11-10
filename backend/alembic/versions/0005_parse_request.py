"""Keep the last successful classification visible during reprocessing."""
import sqlalchemy as sa
from alembic import op

revision="0005"
down_revision="0004"
branch_labels=depends_on=None

def upgrade():
    op.add_column("source_documents",sa.Column("requested_kind",sa.String(),nullable=True))

def downgrade():
    op.drop_column("source_documents","requested_kind")
