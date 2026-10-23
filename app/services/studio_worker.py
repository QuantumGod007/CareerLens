"""Worker handlers: expensive parsing, model calls and rendering never hold write transactions."""
import json
from uuid import UUID, uuid4, uuid5

from sqlalchemy import func, select

from app.core.errors import DomainError
from app.persistence.models import (ProfileVersion, Fact, ResumeUpload, Search, SearchResult, SourceBoard,
    SourceListing, JobSnapshot, JobAnalysis, ResumeGeneration, ResumeVersion)
from app.schemas.ai import TailoredContent, VerificationResult
from app.schemas.studio import ResumeContent
from app.services.artifacts import ArtifactStore
from app.services.events import append_event
from app.services.matching import PIPELINE, analyse_jd, assess, role_matches, role_warning
from app.services.pdf_render import render_resume
from app.services.profile_parser import extract_pdf, parse_profile
from app.services.studio import (facts_view, owned_profile, current_job)
from app.services.tailoring import ai_input, deterministic_violations, semantic_issues, restore_or_block
from app.adapters.groq_resume import GroqResumeProvider, MODEL, FALLBACK_MODEL, PROMPT_VERSION
from app.adapters.groq_limits import check_cooldown


def parse_resume(worker, task):
    db,queue=worker.db,worker.queue
    with db.read() as session:
        upload=session.get(ResumeUpload,task.entity_id)
        if not upload: raise DomainError('NOT_FOUND','Resume upload not found.',404)
        artifact_id,person=upload.artifact_id,upload.candidate_id
    content=ArtifactStore(db).read(artifact_id,task.session_id)
    pages=extract_pdf(content)
    queue.progress(task.id,'EXTRACTING_SOURCED_FACTS',55)
    profile_id=uuid5(task.entity_id,'profile')
    draft=parse_profile(pages,profile_id)
    from app.services.profile_structuring import structure_profile
    draft,methods,parsing=structure_profile(worker,task,pages,draft,artifact_id,profile_id)
    def publish(session,current):
        version=(session.scalar(select(func.max(ProfileVersion.version)).where(ProfileVersion.candidate_id==person)) or 0)+1
        session.add(ProfileVersion(id=profile_id,candidate_id=person,version=version,source_artifact_id=artifact_id,
            profile_json={**draft.model_dump(mode='json'),'pages':pages,'schema_version':'profile-v1','parsing':parsing}))
        session.flush()
        for index,fact in enumerate(draft.facts):
            session.add(Fact(id=fact.id,profile_version_id=profile_id,kind=fact.kind,
                value_json={'text':str(fact.value),'stable_id':str(fact.id),'order':index,'extraction_method':methods[str(fact.id)]},provenance='extracted',
                source_ref=fact.source_ref.model_dump(mode='json')))
        row=session.get(ResumeUpload,task.entity_id)
        row.state,row.profile_version_id='READY',profile_id
        append_event(session,'profile',profile_id,task.correlation_id,'PARSED',count=len(draft.facts),revision=1)
    queue.complete_studio(task.id,{'entity_type':'resume_upload','entity_id':str(task.entity_id),'profile_version_id':str(profile_id)},publish)


def search_jobs(worker,task):
    db,queue=worker.db,worker.queue
    with db.read() as session:
        search=session.get(Search,task.entity_id)
        if not search: raise DomainError('NOT_FOUND','Search not found.',404)
        owned_profile(session,search.profile_version_id,task.session_id,confirmed=True,current=True)
        facts=facts_view(session,search.profile_version_id)
        warning=role_warning(search.title,facts)
        needs_decision=bool(warning and search.metadata_json.get('decision')!='continue_requested_role')
        results=[]
        if not needs_decision:
            query=select(JobSnapshot).join(SourceListing,SourceListing.job_snapshot_id==JobSnapshot.id).join(
                SourceBoard,SourceBoard.id==JobSnapshot.source_board_id).where(SourceBoard.enabled.is_(True)).order_by(JobSnapshot.title,JobSnapshot.id)
            seen=set()
            for job in session.scalars(query):
                filters=search.filters
                if job.canonical_job_key in seen or not role_matches(search.title,job.title): continue
                if filters.get('location') and filters['location'].strip().casefold() not in (job.location or '').casefold(): continue
                if filters.get('employment_type') and filters['employment_type'].strip().casefold()!=(job.employment_type or '').casefold(): continue
                remote=filters.get('remote')
                workplace=job.structured_json.get('workplace_type')
                if remote is True and workplace!='remote': continue
                if remote is False and workplace not in ('on-site','onsite','hybrid'): continue
                seen.add(job.canonical_job_key)
                structured=analyse_jd(job.raw_text,job.title,job.employer)
                assessment=assess(facts,structured)
                matched=sum(s['status']=='supported' for s in assessment['required'])
                results.append((job.id,matched,f"Requested title matched. {matched} of {len(assessment['required'])} extracted required skills have confirmed evidence; review eligibility separately."))
            results=sorted(results,key=lambda row:-row[1])[:5]
        state='NEEDS_ROLE_DECISION' if needs_decision else 'COMPLETED'
        revision=search.revision
    def publish(session,current):
        row=session.get(Search,task.entity_id)
        owned_profile(session,row.profile_version_id,task.session_id,confirmed=True,current=True)
        if row.revision!=revision or row.state!='RUNNING':
            raise DomainError('STALE_REVISION','Search changed while processing.')
        for identifier,_,_ in results:
            current_job(session,identifier)
            session.add(SearchResult(search_id=row.id,job_snapshot_id=identifier))
        row.state,row.revision=state,row.revision+1
        row.metadata_json={**row.metadata_json,'warning':warning,'reason':'no_matching_stored_jobs' if not results and not needs_decision else None,
                           'explanations':{str(identifier):explanation for identifier,_,explanation in results}}
        append_event(session,'search',row.id,task.correlation_id,state,count=len(results),revision=row.revision)
    queue.complete_studio(task.id,{'entity_type':'search','entity_id':str(task.entity_id),'state':state,'result_count':len(results)},publish)


def analyse_job(worker,task):
    db,queue=worker.db,worker.queue
    with db.read() as session:
        search=session.get(Search,UUID(task.input_json['search_id']))
        if not search: raise DomainError('NOT_FOUND','Search not found.',404)
        owned_profile(session,search.profile_version_id,task.session_id,confirmed=True,current=True)
        job=current_job(session,UUID(task.input_json['job_snapshot_id']))
        facts=facts_view(session,search.profile_version_id)
        structured=analyse_jd(job.raw_text,job.title,job.employer)
        assessment=assess(facts,structured)
        search_id,profile_id,job_id,content_hash=search.id,search.profile_version_id,job.id,job.content_hash
    queue.progress(task.id,'MATCHING_CONFIRMED_EVIDENCE',70)
    def publish(session,current):
        owned_profile(session,profile_id,task.session_id,confirmed=True,current=True)
        current_job(session,job_id)
        session.add(JobAnalysis(id=task.entity_id,search_id=search_id,profile_version_id=profile_id,
            job_snapshot_id=job_id,content_hash=content_hash,analysis_json=structured.model_dump(mode='json'),
            assessment_json=assessment,pipeline_version=PIPELINE))
    queue.complete_studio(task.id,{'entity_type':'job_analysis','entity_id':str(task.entity_id)},publish)


def generate_resume(worker,task):
    db,queue=worker.db,worker.queue
    with db.read() as session:
        generation=session.get(ResumeGeneration,task.entity_id)
        if not generation: raise DomainError('NOT_FOUND','Resume generation not found.',404)
        if not generation.consent_at or generation.consent_version!='groq-resume-v2':
            raise DomainError('AI_CONSENT_REQUIRED','Consent must be recorded before a model call.',400)
        profile=owned_profile(session,generation.profile_version_id,task.session_id,confirmed=True,current=True)
        analysis=session.get(JobAnalysis,generation.analysis_id)
        current_job(session,analysis.job_snapshot_id)
        facts=facts_view(session,profile.id)
        from app.schemas.ai import StructuredJD
        structured=StructuredJD.model_validate_json(json.dumps(analysis.analysis_json))
        assessment=analysis.assessment_json
        profile_id,job_id,analysis_id=profile.id,analysis.job_snapshot_id,analysis.id
        if generation.stage_json.get('phase','').endswith('_SENDING'):
            raise DomainError('PROVIDER_OUTCOME_UNKNOWN','An interrupted provider call is not replayed automatically. Start a new generation explicitly.',409)
    provider=worker.provider or GroqResumeProvider(db.settings)
    if isinstance(provider, GroqResumeProvider) and generation.stage_json.get('fallback_used'):
        provider.model, provider.fallback_used = FALLBACK_MODEL, True
    payload=ai_input(facts,structured)
    if len(json.dumps(payload))>24000:
        raise DomainError('AI_INPUT_LIMIT','The profile/JD exceeds the bounded AI input. Nothing was sent.',422)

    def call(purpose,schema,request):
        with db.write() as session:
            queue.owned(session,task.id)
            row=session.get(ResumeGeneration,task.entity_id)
            stage=row.stage_json
            if purpose in stage.get('results',{}):
                return schema.model_validate_json(json.dumps(stage['results'][purpose]))
            check_cooldown(session)
            if stage.get('phase','').endswith('_SENDING'):
                raise DomainError('PROVIDER_OUTCOME_UNKNOWN','Provider outcome is uncertain; explicit retry is required.')
            calls=stage.get('calls',0)
            if calls>=5: raise DomainError('REPAIR_EXHAUSTED','The bounded provider-call budget was exhausted.',422)
            repair_count=stage.get('repair_count',0)+(1 if purpose=='REPAIR' else 0)
            if repair_count>1:raise DomainError('REPAIR_EXHAUSTED','Only one controlled repair is permitted.',422)
            row.state='RUNNING'
            row.stage_json={**stage,'phase':purpose+'_SENDING','calls':calls+1,'repair_count':repair_count,'provider':provider.provider_name}
        def before_fallback(report):
            with db.write() as session:
                queue.owned(session,task.id)
                row=session.get(ResumeGeneration,task.entity_id)
                if row.stage_json.get('fallback_used') or row.stage_json.get('calls',0)>=5:
                    raise DomainError('REPAIR_EXHAUSTED','The single model fallback budget was exhausted.',422)
                row.stage_json={**row.stage_json,'fallback_used':True,'calls':row.stage_json.get('calls',0)+1,
                    'diagnostics':{**row.stage_json.get('diagnostics',{}),purpose:[report]}}
        if isinstance(provider, GroqResumeProvider):
            provider.before_fallback=before_fallback
        def save_diagnostics(session,row):
            reports=getattr(provider,'diagnostics',[])
            deadlines=[report['retry_not_before'] for report in reports if report['http_status']==429 and report.get('retry_not_before')]
            stage={**row.stage_json,'diagnostics':{**row.stage_json.get('diagnostics',{}),purpose:reports}}
            if deadlines:
                stage['retry_not_before']=max([stage.get('retry_not_before') or '',*deadlines])
            row.stage_json=stage
        # Persist the call boundary before the external request. No transaction stays open.
        try:
            result=provider.complete(schema,request,purpose)
        except DomainError:
            with db.write() as session:
                queue.owned(session,task.id)
                save_diagnostics(session,session.get(ResumeGeneration,task.entity_id))
            raise
        with db.write() as session:
            queue.owned(session,task.id)
            row=session.get(ResumeGeneration,task.entity_id)
            save_diagnostics(session,row)
            row.stage_json={**row.stage_json,'phase':purpose+'_STORED',
                'models':{**row.stage_json.get('models',{}),purpose:getattr(provider,'model',MODEL)},
                'results':{**row.stage_json.get('results',{}),purpose:result.model_dump(mode='json',by_alias=True)}}
        return result

    queue.progress(task.id,'GROQ_DRAFTING',25)
    draft=call('DRAFT',TailoredContent,payload)
    def verification_payload(value):
        referenced = {str(identifier) for claim in value.claims for identifier in claim.source_fact_ids}
        referenced.update(claim.item_id for claim in value.claims)
        return {'facts': [fact for fact in payload['facts'] if fact['id'] in referenced],
                'draft': value.model_dump(mode='json')}
    queue.progress(task.id,'VERIFYING_CLAIMS',50)
    issues=deterministic_violations(draft,facts)
    semantic=call('VERIFY',VerificationResult,verification_payload(draft))
    issues+=semantic_issues(semantic,draft)
    findings=list(issues)
    if issues:
        queue.progress(task.id,'CONTROLLED_REPAIR',60)
        draft=call('REPAIR',TailoredContent,{**payload,'previous_draft':draft.model_dump(mode='json'),
            'violations':[issue.model_dump(mode='json') for issue in issues]})
        issues=deterministic_violations(draft,facts)
        semantic=call('VERIFY_REPAIR',VerificationResult,verification_payload(draft))
        issues+=semantic_issues(semantic,draft)
        findings+=issues
    verification=VerificationResult.model_validate({'pass':not issues,'violations':issues,'uncertain_claims':[]})
    with db.write() as session:
        queue.owned(session,task.id)
        session.get(ResumeGeneration,task.entity_id).verification_json=verification.model_dump(mode='json',by_alias=True)
        repair_count=session.get(ResumeGeneration,task.entity_id).stage_json.get('repair_count',0)
        stage=session.get(ResumeGeneration,task.entity_id).stage_json
        stage_models=stage.get('models',{})
        actual_model=stage_models.get('REPAIR',stage_models.get('DRAFT',MODEL))
    final,reverted=restore_or_block(draft,facts,issues)
    verification=VerificationResult.model_validate({'pass':True,'violations':[],'uncertain_claims':[]})
    queue.progress(task.id,'RENDERING_VERIFIED_PDF',80)
    pdf,checks=render_resume(facts,final)
    queue.progress(task.id,'CHECKING_PDF_ROUNDTRIP',95)
    content=ResumeContent(tailored=final,verification=verification,reverted_item_ids=reverted,
        review_findings=findings,repair_count=repair_count,
        original_assessment=assessment,tailored_assessment=assessment,pdf_checks=checks,
        provider=provider.provider_name,model=actual_model,stage_models=stage_models,fallback_used=stage.get('fallback_used',False),
        pipeline_version=PIPELINE,prompt_version=PROMPT_VERSION,schema_version='resume-v2')
    artifact=ArtifactStore(db).store(pdf,task.session_id,'application/pdf')
    resume_id=uuid4()
    def publish(session,current):
        owned_profile(session,profile_id,task.session_id,confirmed=True,current=True)
        current_job(session,job_id)
        analysis=session.get(JobAnalysis,analysis_id)
        search=session.get(Search,analysis.search_id)
        if search.metadata_json.get('selected_analysis_id')!=str(analysis_id):
            raise DomainError('STALE_JOB','The selected job changed during generation.')
        session.add(ResumeVersion(id=resume_id,profile_version_id=profile_id,job_snapshot_id=job_id,
            pdf_artifact_id=artifact.id,content_json=content.model_dump(mode='json',by_alias=True),pipeline_version=PIPELINE))
        session.flush()
        row=session.get(ResumeGeneration,task.entity_id)
        row.state,row.resume_version_id,row.error_code='VERIFIED',resume_id,None
        row.verification_json=verification.model_dump(mode='json',by_alias=True)
        row.stage_json={**row.stage_json,'phase':'COMPLETE'}
    queue.complete_studio(task.id,{'entity_type':'resume_generation','entity_id':str(task.entity_id),
        'resume_version_id':str(resume_id),'artifact_id':str(artifact.id)},publish)


HANDLERS={'resume_parse':parse_resume,'job_search':search_jobs,'jd_analysis':analyse_job,'resume_generate':generate_resume}
