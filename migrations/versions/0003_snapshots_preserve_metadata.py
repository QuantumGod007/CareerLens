"""Add complete structured snapshots without rewriting existing history.

Revision ID: 0003_snapshots
Revises: 0002_guards
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_snapshots"
down_revision = "0002_guards"
branch_labels = None
depends_on = None
TABLES = ("profile_versions", "job_snapshots", "resume_versions", "facts")


def upgrade():
    op.add_column("job_snapshots", sa.Column("structured_json", sa.JSON(), nullable=False, server_default="{}"))
    # Old content/hash stays immutable; empty metadata means legacy/unassessed.
    # The v2 pipeline creates a new snapshot containing the complete normalized record.
    for table in TABLES:
        op.execute(f"CREATE TRIGGER preserve_{table} BEFORE DELETE ON {table} "
                   "BEGIN SELECT RAISE(ABORT, 'historical versions cannot be deleted'); END")


def downgrade():
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER preserve_{table}")
    op.drop_column("job_snapshots", "structured_json")
