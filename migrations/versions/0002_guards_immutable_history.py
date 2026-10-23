"""Protect historical content and terminal preparation runs.

Revision ID: 0002_guards
Revises: 0001_foundation
"""
from alembic import op

revision = "0002_guards"
down_revision = "0001_foundation"
branch_labels = None
depends_on = None

TRIGGERS = {
    "immutable_profile_content": """BEFORE UPDATE OF candidate_id, version, source_artifact_id, profile_json ON profile_versions
        BEGIN SELECT RAISE(ABORT, 'immutable profile content'); END""",
    "immutable_job_snapshot": """BEFORE UPDATE ON job_snapshots
        BEGIN SELECT RAISE(ABORT, 'immutable job snapshot'); END""",
    "immutable_resume_version": """BEFORE UPDATE ON resume_versions
        BEGIN SELECT RAISE(ABORT, 'immutable resume version'); END""",
    "immutable_fact": """BEFORE UPDATE ON facts
        BEGIN SELECT RAISE(ABORT, 'immutable fact'); END""",
    "events_append_only_update": """BEFORE UPDATE ON events
        BEGIN SELECT RAISE(ABORT, 'events are append only'); END""",
    "events_append_only_delete": """BEFORE DELETE ON events
        BEGIN SELECT RAISE(ABORT, 'events are append only'); END""",
    "terminal_run": """BEFORE UPDATE ON preparation_runs
        WHEN OLD.state IN ('SUBMITTED','NOT_SUBMITTED','CANCELLED','DRY_RUN_READY')
        BEGIN SELECT RAISE(ABORT, 'terminal preparation run'); END""",
    "possible_send_irreversible": """BEFORE UPDATE OF send_started_at ON applications
        WHEN OLD.send_started_at IS NOT NULL AND NEW.send_started_at IS NOT OLD.send_started_at
        BEGIN SELECT RAISE(ABORT, 'possible send cannot be reset'); END""",
}


def upgrade():
    for name, body in TRIGGERS.items():
        op.execute(f"CREATE TRIGGER {name} {body}")


def downgrade():
    for name in reversed(TRIGGERS):
        op.execute(f"DROP TRIGGER {name}")
