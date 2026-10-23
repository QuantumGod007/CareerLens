from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, Path, Query, Request, Response, UploadFile
from sqlalchemy import select

from app.core.errors import DomainError
from app.core.security import local_session
from app.persistence.models import ProfileVersion, Candidate, Search, ResumeGeneration, Task, ResumeVersion
from app.schemas.api import TaskReference
from app.schemas.studio import (ProfileView, ProfileSummary, CorrectionCommand, RevisionCommand, SearchCommand,
    DecisionCommand, SelectionCommand, SearchView, AnalysisView, GenerationCommand, GenerationView, GenerationSummary)
from app.services import studio
from app.services.artifacts import ArtifactStore
from app.services.pdf_render import preview

router=APIRouter(prefix='/api/v1',tags=['resume studio'])
Key=Annotated[str,Header(alias='Idempotency-Key',min_length=1,max_length=100,pattern=r'^[A-Za-z0-9._:-]+$')]
Owner=Annotated[UUID,Depends(local_session)]


def correlation(request):
    return UUID(request.state.correlation_id)


@router.post('/profiles',status_code=202,response_model=TaskReference)
async def upload_profile(request: Request, idempotency_key: Key, owner: Owner, resume: UploadFile=File()):
    try:
        content=await resume.read(5*1024*1024+1)
    finally:
        await resume.close()
    if len(content)>5*1024*1024:
        raise DomainError('PDF_TOO_LARGE','PDFs must be no larger than 5 MiB.',413)
    if not content.startswith(b'%PDF-'):
        raise DomainError('UNREADABLE_PDF','Choose an actual text-based PDF.',415)
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(studio.upload,request.app.state.database,owner,correlation(request),idempotency_key,content)


@router.get('/profiles',response_model=list[ProfileSummary])
def profiles(request: Request,owner: Owner,offset: Annotated[int,Query(ge=0)]=0):
    with request.app.state.database.read() as session:
        return list(session.scalars(select(ProfileVersion).join(Candidate,Candidate.id==ProfileVersion.candidate_id)
            .where(Candidate.session_id==owner).order_by(ProfileVersion.version.desc()).offset(offset).limit(20)))


@router.get('/profiles/{profile_id}',response_model=ProfileView)
def profile(profile_id: UUID,request: Request,owner: Owner):
    with request.app.state.database.read() as session:
        return studio.profile_view(session,studio.owned_profile(session,profile_id,owner))


@router.patch('/profiles/{profile_id}',response_model=ProfileView,status_code=201)
def correct(profile_id: UUID,command: CorrectionCommand,request: Request,idempotency_key: Key,owner: Owner):
    return studio.command(request.app.state.database,owner,f'/api/v1/profiles/{profile_id}',idempotency_key,
        command.model_dump(mode='json'),lambda session:studio.correct_profile(session,owner,profile_id,command,correlation(request)),201)


@router.post('/profiles/{profile_id}/confirm',response_model=ProfileView)
def confirm(profile_id: UUID,command: RevisionCommand,request: Request,idempotency_key: Key,owner: Owner):
    return studio.command(request.app.state.database,owner,f'/api/v1/profiles/{profile_id}/confirm',idempotency_key,
        command.model_dump(mode='json'),lambda session:studio.confirm_profile(session,owner,profile_id,command.expected_revision,correlation(request)))


@router.post('/searches',response_model=TaskReference,status_code=202)
def search(command: SearchCommand,request: Request,idempotency_key: Key,owner: Owner):
    return studio.command(request.app.state.database,owner,'/api/v1/searches',idempotency_key,
        command.model_dump(mode='json'),lambda session:studio.start_search(session,owner,correlation(request),command),202)


@router.get('/searches',response_model=list[SearchView])
def searches(request: Request,owner: Owner,offset: Annotated[int,Query(ge=0)]=0):
    with request.app.state.database.read() as session:
        rows=session.scalars(select(Search).join(ProfileVersion,ProfileVersion.id==Search.profile_version_id)
            .join(Candidate,Candidate.id==ProfileVersion.candidate_id).where(Candidate.session_id==owner)
            .order_by(Search.created_at.desc(),Search.id).offset(offset).limit(20))
        return [studio.search_view(session,row) for row in rows]


@router.get('/searches/{search_id}',response_model=SearchView)
def get_search(search_id: UUID,request: Request,owner: Owner):
    with request.app.state.database.read() as session:
        return studio.search_view(session,studio.owned_search(session,search_id,owner))


@router.post('/searches/{search_id}/decision',response_model=TaskReference,status_code=202)
def decision(search_id: UUID,command: DecisionCommand,request: Request,idempotency_key: Key,owner: Owner):
    return studio.command(request.app.state.database,owner,f'/api/v1/searches/{search_id}/decision',idempotency_key,
        command.model_dump(mode='json'),lambda session:studio.decide_search(session,owner,correlation(request),search_id,command),202)


@router.post('/searches/{search_id}/selection',response_model=TaskReference,status_code=202)
def selection(search_id: UUID,command: SelectionCommand,request: Request,idempotency_key: Key,owner: Owner):
    return studio.command(request.app.state.database,owner,f'/api/v1/searches/{search_id}/selection',idempotency_key,
        command.model_dump(mode='json'),lambda session:studio.select_job(session,owner,correlation(request),search_id,command),202)


@router.get('/job-analyses/{analysis_id}',response_model=AnalysisView)
def analysis(analysis_id: UUID,request: Request,owner: Owner):
    with request.app.state.database.read() as session:
        return studio.analysis_view(session,studio.owned_analysis(session,analysis_id,owner))


@router.post('/resume-generations',response_model=TaskReference,status_code=202)
def generation(command: GenerationCommand,request: Request,idempotency_key: Key,owner: Owner):
    return studio.command(request.app.state.database,owner,'/api/v1/resume-generations',idempotency_key,
        command.model_dump(mode='json'),lambda session:studio.generate(session,owner,correlation(request),command),202)


@router.get('/resume-generations',response_model=list[GenerationSummary])
def generations(request: Request,owner: Owner,offset: Annotated[int,Query(ge=0)]=0):
    with request.app.state.database.read() as session:
        return list(session.scalars(select(ResumeGeneration).join(Candidate,Candidate.id==ResumeGeneration.candidate_id)
            .where(Candidate.session_id==owner).order_by(ResumeGeneration.created_at.desc(),ResumeGeneration.id).offset(offset).limit(20)))


@router.get('/resume-generations/{generation_id}',response_model=GenerationView)
def get_generation(generation_id: UUID,request: Request,owner: Owner):
    with request.app.state.database.read() as session:
        return studio.generation_view(session,studio.owned_generation(session,generation_id,owner))


@router.get('/resume-generations/{generation_id}/preview/{page}',response_class=Response,
    responses={200:{'content':{'image/png':{}},'description':'Private raster preview of a verified generated PDF page'}})
def pdf_preview(generation_id: UUID,page: Annotated[int,Path(ge=1,le=25)],request: Request,owner: Owner):
    with request.app.state.database.read() as session:
        row=studio.owned_generation(session,generation_id,owner)
        if row.state!='VERIFIED' or not row.resume_version_id:
            raise DomainError('PDF_NOT_READY','A verified PDF is not available yet.')
        resume=session.get(ResumeVersion,row.resume_version_id)
        if page>resume.content_json['pdf_checks']['pages']:
            raise DomainError('NOT_FOUND','PDF page not found.',404)
        artifact_id=resume.pdf_artifact_id
    return Response(preview(ArtifactStore(request.app.state.database).read(artifact_id,owner),page),media_type='image/png')


@router.get('/studio/tasks',response_model=list[TaskReference])
def studio_tasks(request: Request,owner: Owner):
    with request.app.state.database.read() as session:
        rows=session.scalars(select(Task).where(Task.session_id==owner,Task.kind.in_(('resume_parse','job_search','jd_analysis','resume_generate')))
                            .order_by(Task.created_at.desc(),Task.id).limit(20))
        return [{'task_id':task.id,'entity_type':task.entity_type,'entity_id':task.entity_id,'status_url':f'/api/v1/tasks/{task.id}'} for task in rows]
