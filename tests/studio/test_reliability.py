import io
import json
import multiprocessing
import time
from datetime import timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pypdf import PdfReader, PdfWriter
from sqlalchemy import func, select

from app.core.config import Settings
from app.persistence.database import Database
from app.persistence.models import (Artifact, Candidate, ProfileVersion, ResumeGeneration,
                                    ResumeUpload, ResumeVersion, Task, WorkerHeartbeat, utcnow)
from app.schemas.ai import VerificationResult
from app.services.profile_parser import extract_pdf
from app.services.tasks import Queue
from app.worker import Worker
from .helpers import ControlledProvider
from .test_pipeline import (resume_pdf, profile, confirmed, selected, send, completed, generation)


def paused_worker(directory, marker, stage):
    settings = Settings(data_dir=Path(directory), heartbeat_seconds=.1, lease_seconds=1)
    database = Database(settings)

    def pause():
        Path(marker).write_text('Inside controlled stage; no live provider call')
        time.sleep(30)

    class PausedProvider(ControlledProvider):
        def complete(self, *args):
            pause()
            return super().complete(*args)

    if stage == 'parse':
        from app.services import studio_worker
        original = studio_worker.extract_pdf

        def paused_extract(data):
            pause()
            return original(data)

        studio_worker.extract_pdf = paused_extract
    Worker(database, provider=PausedProvider()).run(once=True)


@pytest.mark.parametrize('stage', ['parse', 'provider'])
def test_real_worker_process_kill_recovers_parse_but_never_replays_provider(
        stage, client, headers, database, settings, selected, resume_pdf, tmp_path):
    if stage == 'parse':
        response = send(client, headers, '/api/v1/profiles',
                        files={'resume': ('synthetic.pdf', resume_pdf, 'application/pdf')})
    else:
        response = generation(client, headers, selected)
    reference = response.json()
    marker = tmp_path / 'paused.txt'
    process = multiprocessing.get_context('spawn').Process(
        target=paused_worker, args=(str(settings.data_dir), str(marker), stage))
    process.start()
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.05)
        assert marker.exists()
        process.kill()
        process.join(timeout=5)
        with database.read() as session:
            lease = session.get(WorkerHeartbeat, 'primary').lease_expires_at.timestamp()
            assert session.get(Task, UUID(reference['task_id'])).status == 'RUNNING'
        time.sleep(max(0, lease - time.time()) + .15)
        provider = ControlledProvider()
        Worker(database, provider=provider).run(once=True)
        result = client.get(reference['status_url'], headers=headers).json()
        if stage == 'parse':
            assert result['status'] == 'SUCCEEDED' and result['attempts'] == 2
            with database.read() as session:
                upload = session.get(ResumeUpload, UUID(reference['entity_id']))
                assert upload.state == 'READY' and upload.profile_version_id
            assert not provider.calls
        else:
            assert result['status'] == 'FAILED' and result['error_code'] == 'PROVIDER_OUTCOME_UNKNOWN'
            assert not provider.calls
            with database.read() as session:
                row = session.get(ResumeGeneration, UUID(reference['entity_id']))
                assert row.state == 'FAILED' and row.resume_version_id is None
                assert session.scalar(select(func.count()).select_from(ResumeVersion)) == 0
        original_id = selected[0]['source_artifact_id']
        assert client.get('/api/v1/artifacts/' + original_id, headers=headers).content == resume_pdf
    finally:
        if process.is_alive():
            process.kill()
        process.join(timeout=5)


def test_exhausted_recovery_finishes_upload_resource_without_false_profile(client, headers, database, resume_pdf):
    response = send(client, headers, '/api/v1/profiles',
                    files={'resume': ('synthetic.pdf', resume_pdf, 'application/pdf')})
    old = Queue(database, uuid4())
    old.start()
    task = old.claim()
    with database.write() as session:
        row = session.get(Task, task.id)
        row.attempts = row.max_attempts
        row.lease_expires_at = utcnow() - timedelta(seconds=1)
    old.stop()
    Worker(database).run(once=True)
    result = client.get(response.json()['status_url'], headers=headers).json()
    assert result['status'] == 'FAILED' and result['error_code'] == 'RETRY_EXHAUSTED'
    with database.read() as session:
        row = session.get(ResumeUpload, UUID(response.json()['entity_id']))
        assert row.state == 'FAILED' and row.error_code == 'RETRY_EXHAUSTED'
        assert row.profile_version_id is None
        assert session.scalar(select(func.count()).select_from(ProfileVersion)) == 0


@pytest.mark.parametrize('active', ['javascript', 'attachment'])
def test_active_pdf_content_is_rejected(resume_pdf, active):
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(resume_pdf)))
    if active == 'javascript':
        writer.add_js("app.alert('synthetic');")
    else:
        writer.add_attachment('synthetic.txt', b'synthetic attachment')
    output = io.BytesIO()
    writer.write(output)
    from app.core.errors import DomainError
    with pytest.raises(DomainError) as error:
        extract_pdf(output.getvalue())
    assert error.value.code == ('PDF_JAVASCRIPT_ACTION' if active=='javascript' else 'PDF_EMBEDDED_FILES')


def test_generated_pdf_preview_checks_ownership_and_hash(client, headers, database, selected):
    response = generation(client, headers, selected)
    completed(client, headers, database, response.json(), ControlledProvider())
    value = client.get('/api/v1/resume-generations/' + response.json()['entity_id'], headers=headers).json()
    with database.read() as session:
        artifact = session.get(Artifact, UUID(value['pdf_artifact_id']))
        path = database.settings.data_dir / 'artifacts' / artifact.relative_path
    path.write_bytes(path.read_bytes() + b'\ntampered')
    assert client.get('/api/v1/artifacts/' + value['pdf_artifact_id'], headers=headers).status_code == 409
    assert client.get(f"/api/v1/resume-generations/{value['id']}/preview/1", headers=headers).status_code == 409
    with database.write() as session:
        session.scalar(select(Candidate)).session_id = uuid4()
    assert client.get('/api/v1/resume-generations/' + value['id'], headers=headers).status_code == 404
    assert client.get('/api/v1/job-analyses/' + value['analysis_id'], headers=headers).status_code == 404
    assert client.get('/api/v1/searches/' + selected[1]['id'], headers=headers).status_code == 404
    assert client.get(f"/api/v1/resume-generations/{value['id']}/preview/1", headers=headers).status_code == 404


def test_semantic_uncertainty_is_repaired_once_then_reverted(client, headers, database, selected):
    class UncertainProvider(ControlledProvider):
        def complete(self, schema, payload, purpose):
            if schema is VerificationResult:
                self.calls.append((purpose, payload))
                claim = payload['draft']['claims'][0]
                return VerificationResult.model_validate_json(json.dumps({
                    'pass': False, 'violations': [], 'uncertain_claims': [{
                        'item_id': claim['item_id'], 'reason': 'Meaning requires review',
                        'source_fact_ids': claim['source_fact_ids']}]}))
            return super().complete(schema, payload, purpose)

    response = generation(client, headers, selected)
    provider = UncertainProvider()
    completed(client, headers, database, response.json(), provider)
    value = client.get('/api/v1/resume-generations/' + response.json()['entity_id'], headers=headers).json()
    assert len(provider.calls) == 4 and value['content']['repair_count'] == 1
    assert value['content']['reverted_item_ids'] and value['content']['review_findings']
    assert value['content']['tailored']['changes'][0]['before'] == value['content']['tailored']['changes'][0]['after']
