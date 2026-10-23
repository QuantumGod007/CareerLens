"""Resume Studio commands and owned, versioned read models."""
import hashlib
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select

from app.core.errors import DomainError
from app.persistence.models import (Artifact, Candidate, Fact, ProfileVersion, ResumeUpload, Search,
    SearchResult, JobSnapshot, SourceBoard, SourceListing, JobAnalysis, ResumeGeneration, ResumeVersion,
    Task, IdempotencyRecord, utcnow)
from app.schemas.studio import ProfileSummary
from app.services.artifacts import ArtifactStore
from app.services.events import append_event
from app.services.idempotency import canonical_hash, previous_response
from app.services.matching import PIPELINE

ACTIVE = ('QUEUED', 'RUNNING', 'WAITING')
CONSENT = 'groq-resume-v2'


def candidate(session, owner):
    row = session.scalar(select(Candidate).where(Candidate.session_id == owner))
    if row is None:
        raise DomainError('NOT_FOUND', 'Local candidate not found.', 404)
    return row


def owned_profile(session, profile_id, owner, *, confirmed=False, current=False):
    row = session.get(ProfileVersion, profile_id)
    if not row or session.get(Candidate, row.candidate_id).session_id != owner:
        raise DomainError('NOT_FOUND', 'Profile not found.', 404)
    if current and row.version != session.scalar(select(func.max(ProfileVersion.version)).where(ProfileVersion.candidate_id == row.candidate_id)):
        raise DomainError('STALE_PROFILE', 'Use the latest profile version and confirm it before continuing.')
    if confirmed and row.confirmed_at is None:
        raise DomainError('PROFILE_UNCONFIRMED', 'Review and confirm this profile first.')
    return row


def owned_search(session, search_id, owner):
    row = session.get(Search, search_id)
    if not row:
        raise DomainError('NOT_FOUND', 'Search not found.', 404)
    owned_profile(session, row.profile_version_id, owner)
    return row


def owned_analysis(session, analysis_id, owner):
    row = session.get(JobAnalysis, analysis_id)
    if not row:
        raise DomainError('NOT_FOUND', 'Job analysis not found.', 404)
    owned_profile(session, row.profile_version_id, owner)
    return row


def owned_generation(session, generation_id, owner):
    row = session.get(ResumeGeneration, generation_id)
    if not row or session.get(Candidate, row.candidate_id).session_id != owner:
        raise DomainError('NOT_FOUND', 'Resume generation not found.', 404)
    return row


def current_job(session, job_id):
    row = session.get(JobSnapshot, job_id)
    if not row or not session.scalar(select(SourceListing).where(SourceListing.job_snapshot_id == job_id)):
        raise DomainError('STALE_JOB', 'The source snapshot changed or the job is no longer in its current listing. Refresh and search again.')
    board = session.get(SourceBoard, row.source_board_id)
    if not board.enabled:
        raise DomainError('SOURCE_DISABLED', 'The selected source is disabled.')
    return row


def facts_view(session, profile_id):
    rows = list(session.scalars(select(Fact).where(Fact.profile_version_id == profile_id).order_by(Fact.created_at, Fact.id)))
    rows.sort(key=lambda row:(row.value_json.get('order', 0),row.created_at,str(row.id)))
    return [{'id': str(f.id), 'stable_id': f.value_json.get('stable_id', str(f.id)), 'kind': f.kind,
             'text': f.value_json['text'], 'provenance': f.provenance, 'source_ref': f.source_ref,
             'extraction_method':f.value_json.get('extraction_method','user' if f.provenance=='user' else 'local')} for f in rows]


def profile_view(session, row):
    return {**ProfileSummary.model_validate(row).model_dump(), 'facts': facts_view(session, row.id),
            'pages': row.profile_json.get('pages', []), 'warnings': row.profile_json.get('warnings', []),
            'parsing':row.profile_json.get('parsing',{'requested_mode':'local','mode':'local'})}


def search_view(session, row):
    results = []
    for job in session.scalars(select(JobSnapshot).join(SearchResult, SearchResult.job_snapshot_id == JobSnapshot.id)
            .where(SearchResult.search_id == row.id).order_by(JobSnapshot.title, JobSnapshot.id)):
        fields = ('id','external_id','canonical_job_key','title','employer','location','employment_type','source_url','apply_url','fetched_at','content_hash')
        board = session.get(SourceBoard, job.source_board_id)
        results.append({**{key: getattr(job,key) for key in fields},
            'match_explanation': row.metadata_json.get('explanations', {}).get(str(job.id), 'Title matched the requested role; review requirements separately.'),
            'source_refreshed_at': board.refreshed_at})
    return {'id': row.id, 'profile_version_id': row.profile_version_id, 'title': row.title,
        'original_title': row.metadata_json.get('original_title', row.title), 'filters': row.filters,
        'state': row.state, 'revision': row.revision, 'warning': row.metadata_json.get('warning'),
        'reason': row.metadata_json.get('reason'), 'task_id': row.metadata_json.get('task_id'),
        'selected_analysis_id': row.metadata_json.get('selected_analysis_id'), 'results': results, 'created_at': row.created_at}


def analysis_view(session, row):
    job = session.get(JobSnapshot, row.job_snapshot_id)
    return {**{name: getattr(row,name) for name in ('id','search_id','profile_version_id','job_snapshot_id','content_hash','pipeline_version','created_at')},
        'job_title': job.title, 'employer': job.employer, 'raw_text': job.raw_text,
        'structured': row.analysis_json, 'assessment': row.assessment_json, 'model': None}


def generation_view(session, row):
    from app.schemas.studio import ResumeContent
    from app.schemas.ai import VerificationResult
    import json
    analysis = session.get(JobAnalysis, row.analysis_id)
    job = session.get(JobSnapshot, analysis.job_snapshot_id)
    profile = session.get(ProfileVersion, row.profile_version_id)
    resume = session.get(ResumeVersion, row.resume_version_id) if row.resume_version_id else None
    artifact = session.get(Artifact, resume.pdf_artifact_id) if resume else None
    names = ('id','profile_version_id','analysis_id','task_id','state','resume_version_id','error_code','created_at','consent_at','consent_version')
    return {**{name: getattr(row,name) for name in names}, 'job_title': job.title, 'employer': job.employer,
        'original_artifact_id': profile.source_artifact_id, 'pdf_artifact_id': artifact.id if artifact else None,
        'pdf_sha256': artifact.sha256 if artifact else None,
        'verification': VerificationResult.model_validate_json(json.dumps(row.verification_json)) if row.verification_json else None,
        'provider_diagnostics': [report for reports in row.stage_json.get('diagnostics', {}).values() for report in reports],
        'content': ResumeContent.model_validate_json(json.dumps(resume.content_json)) if resume else None}


def command(database, owner, route, key, payload, action, status=200):
    digest = canonical_hash(payload)
    with database.write() as session:
        previous = previous_response(session, owner, route, key, digest)
        if previous is not None:
            return previous
        result = action(session)
        # Persist precisely the serialized response used by replay, including UTC timestamps.
        from fastapi.encoders import jsonable_encoder
        result = jsonable_encoder(result)
        session.add(IdempotencyRecord(session_id=owner, route=route, key=key, request_hash=digest,
                                      status_code=status, response_json=result))
        return result


def enqueue(session, owner, correlation, kind, entity_type, entity_id, business=None, payload=None):
    task = session.scalar(select(Task).where(Task.business_key == business, Task.status.in_(ACTIVE))) if business else None
    if task is None:
        task = Task(id=uuid4(), session_id=owner, correlation_id=correlation, kind=kind,
                    entity_type=entity_type, entity_id=entity_id, business_key=business, input_json=payload or {})
        session.add(task)
        session.flush()
        append_event(session, 'task', task.id, correlation, 'QUEUED', step='QUEUED', attempt=0)
    return {'task_id': str(task.id), 'entity_type': task.entity_type, 'entity_id': str(task.entity_id), 'status_url': f'/api/v1/tasks/{task.id}'}


def upload(database, owner, correlation, key, content, *, parsing_mode='local',ai_consent=False,consent_version=None):
    from app.services.profile_structuring import CONSENT as PROFILE_CONSENT
    if parsing_mode not in ('local','groq'):
        raise DomainError('VALIDATION_ERROR','Choose local or Groq profile extraction.',422)
    if parsing_mode=='groq' and (not ai_consent or consent_version!=PROFILE_CONSENT):
        raise DomainError('AI_PROFILE_CONSENT_REQUIRED','Explicit consent to text-only Groq profile structuring is required.',400)
    digest = hashlib.sha256(content).hexdigest()
    payload={'sha256':digest}
    if parsing_mode=='groq':payload.update(parsing_mode='groq',consent_version=PROFILE_CONSENT)
    with database.read() as session:
        previous = previous_response(session, owner, '/api/v1/profiles', key, canonical_hash(payload))
        if previous is not None:
            return previous
    store = ArtifactStore(database)
    artifact = store.store(content, owner, 'application/pdf')
    upload_id = uuid4()
    def create(session):
        person = candidate(session, owner)
        metadata={'parsing_mode':parsing_mode}
        if parsing_mode=='groq':metadata.update(consent_version=PROFILE_CONSENT,consent_at=utcnow().isoformat())
        reference = enqueue(session, owner, correlation, 'resume_parse', 'resume_upload', upload_id,
                            f'parse:{person.id}:{digest}'+(':groq:'+PROFILE_CONSENT if parsing_mode=='groq' else ''),payload=metadata)
        if reference['entity_id'] == str(upload_id):
            session.add(ResumeUpload(id=upload_id, candidate_id=person.id, artifact_id=artifact.id,
                                    task_id=UUID(reference['task_id']), state='QUEUED'))
            if parsing_mode=='groq':append_event(session,'task',UUID(reference['task_id']),correlation,'GROQ_PROFILE_CONSENT',mode='groq')
        return reference
    try:
        result = command(database, owner, '/api/v1/profiles', key, payload, create, 202)
    except BaseException:
        with database.write() as session:
            session.delete(session.get(Artifact, artifact.id))
        store.safe_path(artifact.relative_path).unlink(missing_ok=True)
        raise
    if result['entity_id'] != str(upload_id):
        # Only this freshly created, unpublished artifact is discarded after a concurrent replay.
        with database.write() as session:
            session.delete(session.get(Artifact, artifact.id))
        store.safe_path(artifact.relative_path).unlink(missing_ok=True)
    return result


def correct_profile(session, owner, profile_id, edits, correlation):
    old = owned_profile(session, profile_id, owner, current=True)
    if old.revision != edits.expected_revision:
        raise DomainError('STALE_REVISION', 'Reload the profile before editing it.')
    facts = facts_view(session, old.id)
    values = {f['id']: f for f in facts}
    seen = set()
    for edit in edits.corrections:
        if edit.fact_id:
            key = str(edit.fact_id)
            if key not in values or key in seen:
                raise DomainError('INVALID_FACT', 'Correct each fact from this profile at most once.', 422)
            seen.add(key)
            values[key] = {**values[key], 'kind': edit.kind, 'text': edit.text.strip(), 'provenance': 'user', 'source_ref': None,'extraction_method':'user'}
        else:
            identifier = str(uuid4())
            values[identifier] = {'id': identifier, 'stable_id': identifier, 'kind': edit.kind,
                'text': edit.text.strip(), 'provenance': 'user', 'source_ref': None,'extraction_method':'user'}
    if len(values) > 200 or sum(len(f['text']) for f in values.values()) > 80000 or any(not f['text'] for f in values.values()):
        raise DomainError('PROFILE_TEXT_LIMIT', 'Keep the profile within 200 facts and 80,000 characters.', 422)
    grouped = {kind:[f['text'] for f in values.values() if f['kind']==kind] for kind in ('skills','education','projects','experience')}
    contact = {kind:next((f['text'] for f in values.values() if f['kind']==kind),None) for kind in ('name','email','phone','links')}
    row = ProfileVersion(id=uuid4(), candidate_id=old.candidate_id, version=old.version+1,
        source_artifact_id=old.source_artifact_id, profile_json={**grouped,'contact':contact,'pages':old.profile_json.get('pages',[]),
            'schema_version':'profile-v1','warnings':['Candidate corrections require fresh confirmation.'],
            'parsing':old.profile_json.get('parsing',{'requested_mode':'local','mode':'local'})})
    session.add(row); session.flush()
    for index,fact in enumerate(values.values()):
        identifier = uuid5(row.id, fact['stable_id'])
        session.add(Fact(id=identifier, profile_version_id=row.id, kind=fact['kind'],
            value_json={'text': fact['text'], 'stable_id': fact['stable_id'],'order':index,'extraction_method':fact['extraction_method']}, provenance=fact['provenance'], source_ref=fact['source_ref']))
    append_event(session, 'profile', row.id, correlation, 'CORRECTED', revision=1, count=len(values))
    session.flush()
    return profile_view(session, row)


def confirm_profile(session, owner, profile_id, expected, correlation):
    row = owned_profile(session, profile_id, owner, current=True)
    if row.revision != expected:
        raise DomainError('STALE_REVISION', 'Reload the profile before confirming it.')
    if not facts_view(session,row.id):
        raise DomainError('PROFILE_EMPTY','Add verifiable facts before confirming this profile.',422)
    if row.confirmed_at is None:
        row.confirmed_at, row.revision = utcnow(), row.revision + 1
        append_event(session, 'profile', row.id, correlation, 'CONFIRMED', revision=row.revision)
    return profile_view(session, row)


def start_search(session, owner, correlation, request):
    from app.services.matching import role_tokens
    if not role_tokens(request.preferred_title):
        raise DomainError('ROLE_REQUIRED','Enter an explicit preferred role.',422)
    owned_profile(session, request.profile_version_id, owner, confirmed=True, current=True)
    row = Search(id=uuid4(), profile_version_id=request.profile_version_id, title=request.preferred_title.strip(),
        filters=request.filters.model_dump(), state='RUNNING', metadata_json={'original_title': request.preferred_title.strip()})
    session.add(row); session.flush()
    reference = enqueue(session, owner, correlation, 'job_search', 'search', row.id)
    row.metadata_json = {**row.metadata_json, 'task_id': reference['task_id']}
    append_event(session, 'search', row.id, correlation, 'ROLE_SELECTED', role=row.title)
    return reference


def decide_search(session, owner, correlation, search_id, request):
    row = owned_search(session, search_id, owner)
    owned_profile(session, row.profile_version_id, owner, confirmed=True, current=True)
    if row.revision != request.expected_revision or row.state != 'NEEDS_ROLE_DECISION':
        raise DomainError('STALE_REVISION', 'Reload this search before making a role decision.')
    if request.decision == 'change_role':
        if not request.preferred_title or not request.preferred_title.strip():
            raise DomainError('ROLE_REQUIRED', 'Enter your new preferred role.', 422)
        row.title = request.preferred_title.strip()
    elif request.preferred_title is not None:
        raise DomainError('INVALID_DECISION', 'Continuing a role cannot silently replace its title.', 422)
    row.state, row.revision = 'RUNNING', row.revision+1
    reference = enqueue(session, owner, correlation, 'job_search', 'search', row.id)
    row.metadata_json = {**row.metadata_json, 'task_id': reference['task_id'], 'decision': request.decision}
    append_event(session, 'search', row.id, correlation, 'ROLE_DECISION', role=row.title, decision=request.decision, revision=row.revision)
    return reference


def select_job(session, owner, correlation, search_id, request):
    search = owned_search(session, search_id, owner)
    owned_profile(session, search.profile_version_id, owner, confirmed=True, current=True)
    if search.state != 'COMPLETED' or search.revision != request.expected_revision:
        raise DomainError('STALE_REVISION', 'Reload the completed search before selecting a job.')
    if not session.get(SearchResult, (search.id, request.job_snapshot_id)):
        raise DomainError('INVALID_SEARCH_RESULT', 'Select a job returned by this search.', 422)
    current_job(session, request.job_snapshot_id)
    analysis_id = uuid4()
    reference = enqueue(session, owner, correlation, 'jd_analysis', 'job_analysis', analysis_id,
                        f'analysis:{search.id}:{request.job_snapshot_id}',
                        payload={'search_id': str(search.id), 'job_snapshot_id': str(request.job_snapshot_id)})
    search.metadata_json = {**search.metadata_json, 'selected_job_id': str(request.job_snapshot_id),
                            'selected_analysis_id': reference['entity_id']}
    search.revision += 1
    append_event(session, 'search', search.id, correlation, 'JOB_SELECTED', revision=search.revision)
    return reference


def generate(session, owner, correlation, request):
    from app.adapters.groq_resume import MODEL, FALLBACK_MODEL, PROMPT_VERSION
    from app.adapters.groq_limits import check_cooldown
    if not request.consent:
        raise DomainError('AI_CONSENT_REQUIRED', 'Consent to Groq processing is required before sending candidate content.', 400)
    profile = owned_profile(session, request.profile_version_id, owner, confirmed=True, current=True)
    analysis = owned_analysis(session, request.analysis_id, owner)
    if analysis.profile_version_id != profile.id:
        raise DomainError('STALE_PROFILE', 'Analyse the job against the current confirmed profile.')
    job = current_job(session, analysis.job_snapshot_id)
    search = session.get(Search, analysis.search_id)
    if search.metadata_json.get('selected_analysis_id') != str(analysis.id):
        raise DomainError('STALE_JOB', 'The selected job changed. Review its latest analysis.')
    digest = canonical_hash({'profile': str(profile.id), 'analysis': str(analysis.id), 'job': job.content_hash,
                             'pipeline': PIPELINE, 'consent': CONSENT,'provider':'groq','model':MODEL,
                             'prompt_version':PROMPT_VERSION,'schema_version':'resume-v2','fallback_model':FALLBACK_MODEL})
    previous = session.scalar(select(ResumeGeneration).where(ResumeGeneration.input_hash == digest,
        ResumeGeneration.candidate_id == profile.candidate_id, ResumeGeneration.state == 'VERIFIED'))
    if previous:
        task = session.get(Task, previous.task_id)
        return {'task_id': str(task.id), 'entity_type': task.entity_type, 'entity_id': str(task.entity_id), 'status_url': f'/api/v1/tasks/{task.id}'}
    check_cooldown(session)
    identifier = uuid4()
    reference = enqueue(session, owner, correlation, 'resume_generate', 'resume_generation', identifier, f'generate:{digest}')
    if reference['entity_id'] == str(identifier):
        session.add(ResumeGeneration(id=identifier, candidate_id=profile.candidate_id, profile_version_id=profile.id,
            analysis_id=analysis.id, task_id=UUID(reference['task_id']), state='QUEUED', consent_at=utcnow(),
            consent_version=CONSENT, input_hash=digest, stage_json={'provider':'groq','model':MODEL,
                'prompt_version':PROMPT_VERSION,'schema_version':'resume-v2','pipeline_version':PIPELINE,'repair_count':0,'fallback_used':False}))
        append_event(session, 'resume_generation', identifier, correlation, 'GROQ_CONSENT', revision=1)
    return reference
