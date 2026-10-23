from uuid import uuid4

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, identity
from app.persistence.database import Database
from app.persistence.models import Candidate, ProfileVersion, JobSnapshot, Event, utcnow
from app.tools.init_db import initialize, migrate


def test_schema_migrations_are_repeatable_and_persistent(database, settings):
    tables = set(inspect(database.engine).get_table_names())
    assert {"candidates", "profile_versions", "facts", "source_boards", "job_snapshots", "searches",
            "search_results", "resume_versions", "applications", "preparation_runs", "question_answers",
            "approvals", "tasks", "events", "artifacts", "idempotency_records", "worker_heartbeats"} <= tables
    with database.read() as session:
        candidate = session.scalar(select(Candidate))
        old_id = candidate.id
        assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert session.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert session.execute(text("PRAGMA busy_timeout")).scalar() == 5000
    initialize(settings)
    with Database(settings).read() as session:
        assert session.scalar(select(Candidate)).id == old_id
        assert session.scalar(select(func.count()).select_from(Candidate)) == 1


def test_upgrade_previously_initialized_database(tmp_path):
    settings = Settings(data_dir=tmp_path / "old")
    migrate(settings, "0001_foundation")
    database = Database(settings)
    candidate_id = uuid4()
    with database.write() as session:
        session.add(Candidate(id=candidate_id, session_id=uuid4()))
    migrate(settings)
    with database.read() as session:
        assert session.get(Candidate, candidate_id) is not None
        assert session.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0004_resume_studio"
    database.close()


def test_foreign_keys_unique_constraints_and_rollback(database):
    with pytest.raises(IntegrityError):
        with database.write() as session:
            session.add(ProfileVersion(candidate_id=uuid4(), version=1, profile_json={}))
    with database.read() as session:
        candidate = session.scalar(select(Candidate))
    with pytest.raises(IntegrityError):
        with database.write() as session:
            session.add_all([ProfileVersion(candidate_id=candidate.id, version=1, profile_json={}),
                             ProfileVersion(candidate_id=candidate.id, version=1, profile_json={})])
    with database.read() as session:
        assert session.scalar(select(func.count()).select_from(ProfileVersion)) == 0


def test_profile_corrections_create_versions_and_old_content_cannot_change(database):
    with database.write() as session:
        candidate = session.scalar(select(Candidate))
        first = ProfileVersion(candidate_id=candidate.id, version=1, profile_json={"skills": ["Python"]})
        second = ProfileVersion(candidate_id=candidate.id, version=2, profile_json={"skills": ["Python", "SQL"]})
        session.add_all([first, second])
    with pytest.raises(IntegrityError):
        with database.write() as session:
            session.get(ProfileVersion, first.id).profile_json = {"skills": ["Invented"]}
    with database.read() as session:
        assert session.get(ProfileVersion, first.id).profile_json == {"skills": ["Python"]}
        assert session.get(ProfileVersion, second.id).version == 2
    with pytest.raises(IntegrityError):
        with database.write() as session:
            session.delete(session.get(ProfileVersion, first.id))


def test_events_are_append_only(database):
    with database.write() as session:
        event = Event(entity_type="synthetic", entity_id=uuid4(), correlation_id=uuid4(), kind="TEST", metadata_json={})
        session.add(event)
    with pytest.raises(IntegrityError):
        with database.write() as session:
            session.get(Event, event.id).kind = "REPLACED"
    with pytest.raises(IntegrityError):
        with database.write() as session:
            session.delete(session.get(Event, event.id))
