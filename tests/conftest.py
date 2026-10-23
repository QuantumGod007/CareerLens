from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, identity
from app.main import create_app
from app.persistence.database import Database
from app.tools.init_db import initialize
from scripts.feasibility.test_job_source import parse_job


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "backend", allowed_hosts=("testserver", "127.0.0.1", "localhost"),
                    retry_seconds=0, heartbeat_seconds=0.1, lease_seconds=2)


@pytest.fixture
def database(settings):
    initialize(settings)
    database = Database(settings)
    yield database
    database.close()


@pytest.fixture
def client(database, settings):
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def headers(settings, database):
    return {"X-CareerLens-Token": identity(settings).token, "Idempotency-Key": str(uuid4())}


def synthetic_job(*, title="Engineering Intern", external_id="11111111-1111-4111-8111-111111111111"):
    return parse_job({"id": external_id, "text": title, "categories": {
        "location": "India", "commitment": "Internship"}, "descriptionPlain": "Synthetic fixture JD: Python and SQL",
        "lists": [], "additionalPlain": "Synthetic eligibility", "workplaceType": "remote",
        "hostedUrl": f"https://jobs.lever.co/drivetrain/{external_id}",
        "applyUrl": f"https://jobs.lever.co/drivetrain/{external_id}/apply"}, "2026-10-23T00:00:00+00:00")
