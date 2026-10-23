import json
import subprocess
import sys
from datetime import timedelta
from uuid import UUID,uuid4
from uuid import uuid5
from pydantic import SecretStr

import pytest
from sqlalchemy import func,select

from app.adapters.groq_resume import MODEL
from app.core.errors import DomainError
from app.persistence.models import Artifact,ProfileVersion,Task,utcnow
from app.schemas.profile_ai import GroqProfileDraft
from app.services.profile_parser import extract_pdf,parse_profile,verify_span
from app.services.profile_structuring import model_input,grounded_profile
from app.services.tasks import Queue
from app.worker import Worker
from .test_pipeline import resume_pdf,completed,send

LAYOUT_HTML='''<!doctype html><meta charset="utf-8"><style>
@page {size:A4;margin:20mm} body{font:11pt Arial;color:#172132} h1{font-size:22pt}
.columns{display:grid;grid-template-columns:155px 1fr;gap:26px} h2{font-size:12pt}
.work{margin-top:40px} p{line-height:1.5;margin:5px 0}
</style><h1>Synthetic Candidate</h1><p>candidate@example.invalid · +1 555 123 4567</p>
<div class="columns"><aside><h2>Skills</h2><p>Python, SQL, Git</p><p>FastAPI</p></aside>
<main><h2>Selected work</h2><div class="work"><p>Built a synthetic Python service<br>with SQL and FastAPI.</p>
<p>Community contribution with unclear category.</p><h2>Education</h2><p>Synthetic University, 2024-2026</p></div></main></div>'''


@pytest.fixture(scope='session')
def layout_pdf(tmp_path_factory):
    path=tmp_path_factory.mktemp('profile-layout')/'synthetic-layout.pdf'
    script='''import sys
from pathlib import Path
from playwright.sync_api import sync_playwright
from scripts.feasibility.common import browser_environment
browser_environment()
with sync_playwright() as p:
 with p.chromium.launch() as browser:
  page=browser.new_page();page.set_content(sys.stdin.read());Path(sys.argv[1]).write_bytes(page.pdf(prefer_css_page_size=True))
'''
    subprocess.run([sys.executable,'-c',script,str(path)],input=LAYOUT_HTML,text=True,
                   capture_output=True,check=True,timeout=30)
    return path.read_bytes()


class ProfileProvider:
    provider_name='controlled_fixture'
    model=MODEL
    def __init__(self, mutation=None, error=None):
        self.calls=[];self.mutation=mutation;self.error=error;self.diagnostics=[]
    def complete(self,schema,payload,purpose):
        assert schema is GroqProfileDraft and purpose=='PROFILE'
        self.calls.append(payload)
        if self.error:raise DomainError(self.error,'Synthetic provider error',503)
        facts=[]
        for kind,phrase in [('skills','Python, SQL, Git'),('projects','Built a synthetic Python service\nwith SQL and FastAPI.'),
                            ('other','Community contribution with unclear category.')]:
            for page in payload['pages']:
                if phrase in page['text']:
                    start=page['text'].index(phrase)
                    facts.append({'kind':kind,'source_ref':{'page':page['page'],'start_offset':start,
                        'end_offset':start+len(phrase),'source_text':phrase}})
        assert facts
        value={'facts':facts}
        if self.mutation:self.mutation(value,payload)
        return schema.model_validate_json(json.dumps(value))


def upload(client,headers,content,*,mode='groq',consent=True,key=None):
    data={'parsing_mode':mode}
    if consent:data.update(ai_consent='true',consent_version='groq-profile-v1')
    return client.post('/api/v1/profiles',headers={**headers,'Idempotency-Key':key or str(uuid4())},
                       data=data,files={'resume':('synthetic-layout.pdf',content,'application/pdf')})


def result_profile(client,headers,task):
    return client.get('/api/v1/profiles/'+task['result']['profile_version_id'],headers=headers).json()


def test_multicolumn_wrapped_and_ambiguous_text_becomes_sourced_profile_draft(client,headers,database,layout_pdf):
    response=upload(client,headers,layout_pdf)
    assert response.status_code==202,response.text
    provider=ProfileProvider()
    task=completed(client,headers,database,response.json(),provider)
    profile=result_profile(client,headers,task)
    assert profile['parsing']['mode']=='groq' and profile['parsing']['model']==MODEL
    assert profile['parsing']['prompt_version']=='profile-spans-v1' and profile['confirmed_at'] is None
    assert any(f['kind']=='projects' and '\nwith SQL' in f['text'] for f in profile['facts'])
    assert any(f['kind']=='other' and 'unclear category' in f['text'] for f in profile['facts'])
    assert {f['extraction_method'] for f in profile['facts']}=={'local','groq'}
    assert all(verify_span(profile['pages'],f['source_ref']) for f in profile['facts'])
    assert all(f['provenance']=='extracted' for f in profile['facts'])
    serialized=json.dumps(provider.calls)
    for private in ('Synthetic Candidate','candidate@example.invalid','555 123 4567','%PDF-'):
        assert private not in serialized
    for page in provider.calls[0]['pages']:
        original=next(p['text'] for p in profile['pages'] if p['page']==page['page'])
        assert len(page['text'])==len(original)
    for expected in ('Python, SQL, Git','FastAPI','Synthetic University, 2024-2026'):
        assert any(expected in f['text'] for f in profile['facts'])
    assert client.get('/api/v1/artifacts/'+profile['source_artifact_id'],headers=headers).content==layout_pdf
    rejected=send(client,headers,'/api/v1/searches',{'profile_version_id':profile['id'],'preferred_title':'Backend Engineer'})
    assert rejected.status_code==409 and rejected.json()['error']['code']=='PROFILE_UNCONFIRMED'
    changed=send(client,headers,'/api/v1/profiles/'+profile['id'],{'expected_revision':profile['revision'],
        'corrections':[{'fact_id':profile['facts'][0]['id'],'kind':profile['facts'][0]['kind'],'text':profile['facts'][0]['text']+' reviewed'}]},method='PATCH').json()
    assert changed['id']!=profile['id'] and changed['confirmed_at'] is None
    assert changed['facts'][0]['provenance']=='user' and changed['facts'][0]['extraction_method']=='user'
    assert changed['parsing']['mode']=='groq'


def test_groq_mode_requires_separate_explicit_consent_before_artifact_or_task(client,headers,database,layout_pdf):
    response=upload(client,headers,layout_pdf,consent=False)
    assert response.status_code==400 and response.json()['error']['code']=='AI_PROFILE_CONSENT_REQUIRED'
    with database.read() as session:
        assert session.scalar(select(func.count()).select_from(Artifact))==0
        assert session.scalar(select(func.count()).select_from(Task))==0


def test_default_local_mode_never_calls_provider(client,headers,database,layout_pdf):
    response=upload(client,headers,layout_pdf,mode='local',consent=False)
    provider=ProfileProvider(error='UNEXPECTED_CALL')
    profile=result_profile(client,headers,completed(client,headers,database,response.json(),provider))
    assert profile['parsing']['mode']=='local' and profile['parsing']['model'] is None and not provider.calls


@pytest.mark.parametrize('code',['MISSING_API_KEY','RATE_LIMIT_OR_QUOTA_EXHAUSTED','PROVIDER_COOLDOWN','PROVIDER_TIMEOUT','SCHEMA_INVALID'])
def test_ai_unavailable_retains_honest_local_only_draft(client,headers,database,layout_pdf,code):
    response=upload(client,headers,layout_pdf)
    profile=result_profile(client,headers,completed(client,headers,database,response.json(),ProfileProvider(error=code)))
    assert profile['parsing']['mode']=='local_fallback' and profile['parsing']['error_code']==code
    assert profile['confirmed_at'] is None and all(f['extraction_method']=='local' for f in profile['facts'])
    assert any('No model facts were accepted' in w for w in profile['warnings'])


@pytest.mark.parametrize('attack',['invented_text','bad_end','wrong_page','overlap','contact'])
def test_model_facts_without_exact_visible_source_are_discarded(client,headers,database,layout_pdf,attack,caplog):
    def mutate(value,payload):
        source=value['facts'][0]['source_ref']
        if attack=='invented_text':source['source_text']='Invented Kubernetes qualification'
        if attack=='bad_end':source['end_offset']=80000
        if attack=='wrong_page':source['page']=10
        if attack=='overlap':value['facts'].append(value['facts'][0])
        if attack=='contact':source.update(start_offset=0,end_offset=19,source_text='Synthetic Candidate')
    response=upload(client,headers,layout_pdf)
    profile=result_profile(client,headers,completed(client,headers,database,response.json(),ProfileProvider(mutate)))
    assert profile['parsing']['mode']=='local_fallback' and profile['parsing']['error_code']=='PROFILE_AI_SOURCE_INVALID'
    assert all(f['extraction_method']=='local' for f in profile['facts'])
    assert not any('Kubernetes' in f['text'] for f in profile['facts'])
    assert 'candidate@example.invalid' not in caplog.text and 'Synthetic Candidate' not in caplog.text


@pytest.mark.parametrize('statement',['No Python experience.','Python is not known.'])
def test_ai_cannot_remove_negation_from_a_selected_skill_span(statement):
    raw='Synthetic Candidate\nSkills\n'+statement
    pages=[{'page':1,'text':raw,'start_offset':0,'end_offset':len(raw)}]
    local=parse_profile(pages,uuid4());payload=model_input(pages,local,uuid4())
    start=pages[0]['text'].index('Python')
    response=GroqProfileDraft.model_validate({'facts':[{'kind':'skills','source_ref':{
        'page':1,'start_offset':start,'end_offset':start+6,'source_text':'Python'}}]})
    with pytest.raises(DomainError,match='PROFILE_AI_SOURCE_INVALID'):
        grounded_profile(pages,local,response,uuid4(),payload)


def test_interrupted_profile_model_call_recovers_locally_without_replay(client,headers,database,layout_pdf):
    reference=upload(client,headers,layout_pdf).json()
    old=Queue(database,uuid4());old.start();task=old.claim()
    with database.write() as session:
        row=session.get(Task,task.id);row.input_json={**row.input_json,'ai':{'phase':'SENDING','calls':1}}
        row.lease_expires_at=utcnow()-timedelta(seconds=1)
    old.stop()
    provider=ProfileProvider()
    profile=result_profile(client,headers,completed(client,headers,database,reference,provider))
    assert not provider.calls and profile['parsing']['error_code']=='PROVIDER_OUTCOME_UNKNOWN'
    assert profile['parsing']['mode']=='local_fallback'


def test_local_and_ai_uploads_have_distinct_idempotency_payloads(client,headers,database,layout_pdf):
    key=str(uuid4())
    first=upload(client,headers,layout_pdf,mode='local',consent=False,key=key)
    assert upload(client,headers,layout_pdf,mode='local',consent=False,key=key).json()==first.json()
    assert upload(client,headers,layout_pdf,key=key).status_code==409
    assert upload(client,headers,layout_pdf).json()!=first.json()


@pytest.mark.parametrize('fallback',[False,True])
def test_profile_structuring_uses_strict_sdk_and_preserves_model_policy(client,headers,database,settings,layout_pdf,monkeypatch,fallback):
    from .test_groq_limits import mock_transport,limited,success
    from app.adapters.groq_resume import FALLBACK_MODEL
    settings.groq_key=SecretStr('synthetic-key')
    calls=[]
    fixture=ProfileProvider()
    def handler(request):
        body=json.loads(request.content);calls.append(body['model'])
        assert body['response_format']['json_schema']['strict'] is True
        assert 'Structure the supplied extracted resume text' in body['messages'][0]['content']
        assert 'candidate@example.invalid' not in request.content.decode() and '%PDF-' not in request.content.decode()
        if fallback and len(calls)==1:return limited()
        content=json.loads(body['messages'][1]['content'])
        result=fixture.complete(GroqProfileDraft,content['untrusted_evidence'],'PROFILE')
        return success(body['model'],result.model_dump(mode='json'))
    mock_transport(monkeypatch,handler)
    reference=upload(client,headers,layout_pdf).json()
    profile=result_profile(client,headers,completed(client,headers,database,reference))
    assert profile['parsing']['mode']=='groq' and profile['parsing']['provider']=='groq'
    assert profile['parsing']['model']==(FALLBACK_MODEL if fallback else MODEL)
    assert calls==([MODEL,FALLBACK_MODEL] if fallback else [MODEL])


def test_profile_cooldown_is_shared_and_future_upload_stays_local(client,headers,database,settings,layout_pdf,monkeypatch):
    from .test_groq_limits import mock_transport,limited
    from app.adapters.groq_limits import check_cooldown
    settings.groq_key=SecretStr('synthetic-key')
    calls=[]
    def handler(request):
        calls.append(True);return limited('tokens per minute',retry='90',tokens='0')
    mock_transport(monkeypatch,handler)
    for expected in ('RATE_LIMIT_OR_QUOTA_EXHAUSTED','PROVIDER_COOLDOWN'):
        reference=upload(client,headers,layout_pdf).json()
        profile=result_profile(client,headers,completed(client,headers,database,reference))
        assert profile['parsing']['mode']=='local_fallback' and profile['parsing']['error_code']==expected
    assert len(calls)==1
    with database.read() as session:
        with pytest.raises(DomainError,match='PROVIDER_COOLDOWN'):check_cooldown(session)


def test_stored_validated_profile_response_recovers_without_another_model_call(client,headers,database,layout_pdf):
    reference=upload(client,headers,layout_pdf).json()
    old=Queue(database,uuid4());old.start();task=old.claim()
    namespace=uuid5(task.entity_id,'profile')
    pages=extract_pdf(layout_pdf);local=parse_profile(pages,namespace)
    with database.read() as session:
        from app.persistence.models import ResumeUpload
        artifact=session.get(ResumeUpload,task.entity_id).artifact_id
    response=ProfileProvider().complete(GroqProfileDraft,model_input(pages,local,artifact),'PROFILE')
    with database.write() as session:
        row=session.get(Task,task.id)
        row.input_json={**row.input_json,'ai':{'phase':'STORED','calls':1,'result':response.model_dump(mode='json'),
            'model':MODEL,'provider':'controlled_fixture'}}
        row.lease_expires_at=utcnow()-timedelta(seconds=1)
    old.stop();provider=ProfileProvider(error='UNEXPECTED_CALL')
    profile=result_profile(client,headers,completed(client,headers,database,reference,provider))
    assert not provider.calls and profile['parsing']['mode']=='groq'
    assert profile['id']==str(namespace) and all(verify_span(profile['pages'],f['source_ref']) for f in profile['facts'])


def test_bounded_ai_input_never_truncates_original_source():
    raw='Synthetic Candidate\nProjects\n'+'\n'.join('A synthetic qualification '+('word '*350) for _ in range(15))
    pages=[{'page':1,'text':raw,'start_offset':0,'end_offset':len(raw)}]
    local=parse_profile(pages,uuid4())
    with pytest.raises(DomainError,match='PROFILE_AI_INPUT_LIMIT'):model_input(pages,local,uuid4())
    assert pages[0]['text']==raw
