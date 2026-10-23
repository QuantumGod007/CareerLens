"""Initialize/upgrade the local database without destroying existing data."""
import os
from uuid import NAMESPACE_URL, uuid5

from alembic import command
from alembic.config import Config
from sqlalchemy import select

from app.core.config import ROOT, Settings, identity, load_settings
from app.persistence.database import Database
from app.persistence.models import Candidate, SourceBoard

BOARD_ID = uuid5(NAMESPACE_URL, "careerlens:lever:drivetrain")
HEAD = "0004_resume_studio"


def migrate(settings: Settings, revision: str = "head") -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    database = Database(settings)
    config = Config(str(ROOT / "alembic.ini"))
    try:
        with database.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, revision)
    finally:
        database.close()
    if settings.db_path.exists():
        settings.db_path.chmod(0o600)


def initialize(settings: Settings) -> None:
    local = identity(settings, create=True)
    migrate(settings)
    database = Database(settings)
    try:
        with database.write() as session:
            if session.get(SourceBoard, BOARD_ID) is None:
                session.add(SourceBoard(id=BOARD_ID, family="lever", slug="drivetrain",
                    employer="Drivetrain", allowed_hosts=["api.lever.co", "jobs.lever.co"], enabled=True))
            if session.scalar(select(Candidate).where(Candidate.session_id == local.id)) is None:
                session.add(Candidate(session_id=local.id))
    finally:
        database.close()


if __name__ == "__main__":
    os.umask(0o077)
    initialize(load_settings())
    print("Database migrated and configured source/local session initialized. Credential values omitted.")
