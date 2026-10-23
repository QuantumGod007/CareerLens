"""Add resume studio records; preserve existing profiles, jobs and task history."""
from alembic import op
import sqlalchemy as sa

revision = "0004_resume_studio"
down_revision = "0003_snapshots"
branch_labels = depends_on = None


def upgrade():
    op.add_column("searches", sa.Column("metadata_json", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("tasks", sa.Column("input_json", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table("resume_uploads",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), sa.ForeignKey("candidates.id"), nullable=False, index=True),
        sa.Column("artifact_id", sa.Uuid(), sa.ForeignKey("artifacts.id"), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False, unique=True),
        sa.Column("profile_version_id", sa.Uuid(), sa.ForeignKey("profile_versions.id")),
        sa.Column("state", sa.String(30), nullable=False), sa.Column("error_code", sa.String(80)))
    op.create_table("job_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("search_id", sa.Uuid(), sa.ForeignKey("searches.id"), nullable=False, index=True),
        sa.Column("profile_version_id", sa.Uuid(), sa.ForeignKey("profile_versions.id"), nullable=False),
        sa.Column("job_snapshot_id", sa.Uuid(), sa.ForeignKey("job_snapshots.id"), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("analysis_json", sa.JSON(), nullable=False), sa.Column("assessment_json", sa.JSON(), nullable=False),
        sa.Column("pipeline_version", sa.String(50), nullable=False))
    op.create_table("resume_generations",
        sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), sa.ForeignKey("candidates.id"), nullable=False, index=True),
        sa.Column("profile_version_id", sa.Uuid(), sa.ForeignKey("profile_versions.id"), nullable=False),
        sa.Column("analysis_id", sa.Uuid(), sa.ForeignKey("job_analyses.id"), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.id"), nullable=False, unique=True),
        sa.Column("state", sa.String(30), nullable=False), sa.Column("consent_at", sa.DateTime(), nullable=False),
        sa.Column("consent_version", sa.String(50), nullable=False), sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("stage_json", sa.JSON(), nullable=False), sa.Column("verification_json", sa.JSON()),
        sa.Column("resume_version_id", sa.Uuid(), sa.ForeignKey("resume_versions.id")), sa.Column("error_code", sa.String(80)))
    for action in ("UPDATE", "DELETE"):
        op.execute(f"CREATE TRIGGER immutable_analysis_{action.lower()} BEFORE {action} ON job_analyses "
                   "BEGIN SELECT RAISE(ABORT, 'immutable job analysis'); END")
    op.execute("CREATE TRIGGER terminal_generation BEFORE UPDATE ON resume_generations "
               "WHEN OLD.state = 'VERIFIED' BEGIN SELECT RAISE(ABORT, 'immutable verified generation'); END")


def downgrade():
    op.execute("DROP TRIGGER terminal_generation")
    for action in ("update", "delete"):
        op.execute(f"DROP TRIGGER immutable_analysis_{action}")
    for name in ("resume_generations", "job_analyses", "resume_uploads"):
        op.drop_table(name)
    op.drop_column("searches", "metadata_json")
    op.drop_column("tasks", "input_json")
