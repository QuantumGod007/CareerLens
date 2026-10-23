from alembic import context
from app.core.config import load_settings
from app.persistence.database import Database
from app.persistence.models import Base, UTCDateTime


def render_item(kind, value, autogen_context):
    if kind == "type" and isinstance(value, UTCDateTime):
        return "sa.DateTime()"
    return False


def run(connection):
    context.configure(connection=connection, target_metadata=Base.metadata,
                      render_as_batch=True, compare_type=True, render_item=render_item)
    with context.begin_transaction():
        context.run_migrations()


provided = context.config.attributes.get("connection")
if provided is not None:
    run(provided)
else:
    settings = load_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    database = Database(settings)
    try:
        with database.engine.connect() as connection:
            run(connection)
    finally:
        database.close()
