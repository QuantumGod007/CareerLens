from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.core.config import Settings


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = create_engine(f"sqlite:///{settings.db_path}",
            connect_args={"check_same_thread": False, "timeout": 5}, hide_parameters=True)

        @event.listens_for(self.engine, "connect")
        def configure(connection, record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def read(self):
        with self.sessions() as session:
            yield session

    @contextmanager
    def write(self):
        # Serializes command/claim transactions across threads and processes.
        # No external calls belong inside this context.
        with self.sessions() as session:
            try:
                session.execute(text("BEGIN IMMEDIATE"))
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def ping(self) -> bool:
        try:
            with self.engine.connect() as connection:
                return connection.execute(text("SELECT 1")).scalar() == 1
        except Exception:
            return False

    def close(self):
        self.engine.dispose()
