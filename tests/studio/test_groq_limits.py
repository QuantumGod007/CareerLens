import json
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from uuid import UUID

import groq
import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from app.adapters.groq_limits import diagnostics
from app.adapters.groq_resume import GroqResumeProvider, MODEL, FALLBACK_MODEL
from app.core.errors import DomainError
from app.main import create_app
from app.persistence.models import ResumeGeneration
from app.schemas.ai import VerificationResult, TailoredContent
from app.worker import Worker
from .helpers import ControlledProvider
from .test_pipeline import resume_pdf, profile, confirmed, selected, generation, completed

HEADERS = {'x-ratelimit-limit-requests':'1000', 'x-ratelimit-remaining-requests':'999',
           'x-ratelimit-limit-tokens':'8000', 'x-ratelimit-remaining-tokens':'8000',
           'x-ratelimit-reset-tokens':'0.01s', 'retry-after':'0.01',
           'authorization':'SYNTHETIC_PRIVATE_CREDENTIAL', 'x-untrusted':'candidate@example.invalid'}


def limited(metric='requests per minute', *, shared=False, retry='0.01', tokens='8000'):
    message = f'Rate limit reached for model `{MODEL}` on {metric}: Limit 30, Used 30, Requested 1.'
    if shared:
        message += ' Shared organization-wide quota.'
    message += ' SYNTHETIC_PRIVATE_CREDENTIAL candidate@example.invalid'
    return httpx.Response(429, headers={**HEADERS, 'retry-after':retry,'x-ratelimit-remaining-tokens':tokens},
                          json={'error':{'code':'rate_limit_exceeded','scope':'model','message':message}})


def success(model, content=None):
    return httpx.Response(200,headers=HEADERS,json={'id':'synthetic','object':'chat.completion','created':1,
        'model':model,'choices':[{'index':0,'message':{'role':'assistant','content':json.dumps(content or {
            'pass':True,'violations':[],'uncertain_claims':[]})},'finish_reason':'stop'}],
        'usage':{'prompt_tokens':100,'completion_tokens':50,'total_tokens':150}})


def mock_transport(monkeypatch, handler):
    real=groq.Groq
    def factory(**kwargs):
        assert kwargs['max_retries']==0 and kwargs['base_url']=='https://api.groq.com'
        return real(**kwargs,http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr('app.adapters.groq_resume.groq.Groq',factory)


@pytest.mark.parametrize('case,expected_calls',[
    ('primary',1),('fallback',2),('both_limited',2),('shared',1),('tpm',1),
    ('project',1),('ambiguous_model',1),('large_input',1),('long_wait',1),('no_retry_header',1),('auth',1),('schema',1),
])
def test_bounded_fallback_and_safe_rate_diagnostics(settings,monkeypatch,case,expected_calls,caplog):
    settings.groq_key=SecretStr('SYNTHETIC_PRIVATE_CREDENTIAL')
    calls=[];waits=[]
    def handler(request):
        payload=json.loads(request.content);calls.append(payload)
        assert payload['response_format']['json_schema']['strict'] is True
        if case=='primary' or (len(calls)==2 and case=='fallback'):
            return success(payload['model'])
        if len(calls)==2:return limited()
        if case=='auth':return httpx.Response(401,json={'error':{'message':'private'}})
        if case=='schema':return success(MODEL,{'unexpected':True})
        if case=='shared':return limited(shared=True)
        if case=='tpm':return limited('tokens per minute')
        if case=='project':return httpx.Response(429,headers=HEADERS,json={'error':{'message':'Project quota reached'}})
        if case=='ambiguous_model':
            response=limited();body=json.loads(response.content);body['error'].pop('scope')
            return httpx.Response(429,headers=HEADERS,json=body)
        if case=='large_input':return limited(tokens='20')
        if case=='long_wait':return limited(retry='60')
        if case=='no_retry_header':
            response=limited();del response.headers['retry-after'];return response
        return limited()
    mock_transport(monkeypatch,handler)
    monkeypatch.setattr('app.adapters.groq_resume.time.sleep',lambda seconds:waits.append(seconds))
    provider=GroqResumeProvider(settings)
    if case in ('primary','fallback'):
        assert provider.complete(VerificationResult,{},'VERIFY').passed
    else:
        with pytest.raises(DomainError):provider.complete(VerificationResult,{},'VERIFY')
    assert len(calls)==expected_calls
    assert calls[0]['model']==MODEL
    assert waits==([.01] if expected_calls==2 else [])
    if expected_calls==2:assert calls[1]['model']==FALLBACK_MODEL
    safe=json.dumps(provider.diagnostics)
    assert 'SYNTHETIC_PRIVATE_CREDENTIAL' not in safe+caplog.text
    assert 'candidate@example.invalid' not in safe+caplog.text
    if case=='tpm':assert provider.diagnostics[0]['limiting_factor']=='tokens_per_minute'


def test_retry_after_http_date_is_respected_and_raw_headers_are_discarded():
    now=datetime(2026,10,23,tzinfo=timezone.utc)
    report=diagnostics(429,{'retry-after':format_datetime(now+timedelta(seconds=90)),
                           'x-ratelimit-remaining-tokens':'untrusted private text'},now=now)
    assert report['retry_after_seconds']==90 and report['headers']=={}


@pytest.mark.parametrize('invent', [False, True])
def test_actual_stage_models_persist_and_factual_failure_never_triggers_fallback(
        settings,database,client,headers,selected,monkeypatch,invent):
    settings.groq_key=SecretStr('synthetic-key')
    calls=[]
    def mutate(draft):draft['claims'][0]['section']='summary'
    fixture=ControlledProvider(mutate if invent else None)
    def handler(request):
        payload=json.loads(request.content);calls.append(payload['model'])
        if not invent and len(calls)==1:return limited()
        data=json.loads(payload['messages'][1]['content'])
        schema=VerificationResult if data['purpose'].startswith('VERIFY') else TailoredContent
        result=fixture.complete(schema,data['untrusted_evidence'],data['purpose'])
        return success(payload['model'],result.model_dump(mode='json',by_alias=True))
    mock_transport(monkeypatch,handler)
    response=generation(client,headers,selected)
    Worker(database).run(once=True)
    task=client.get(response.json()['status_url'],headers=headers).json()
    value=client.get('/api/v1/resume-generations/'+response.json()['entity_id'],headers=headers).json()
    if invent:
        assert task['status']=='FAILED' and value['state']=='BLOCKED'
        assert calls==[MODEL]*4 and value['pdf_artifact_id'] is None
    else:
        assert task['status']=='SUCCEEDED' and calls==[MODEL,FALLBACK_MODEL,FALLBACK_MODEL]
        assert value['content']['model']==FALLBACK_MODEL and value['content']['fallback_used']
        assert value['content']['stage_models']=={'DRAFT':FALLBACK_MODEL,'VERIFY':FALLBACK_MODEL}
        with database.read() as session:
            stage=session.get(ResumeGeneration,UUID(value['id'])).stage_json
            assert stage['calls']==3 and stage['fallback_used']


def test_reported_cooldown_survives_api_restart_and_prevents_new_calls(settings,database,client,headers,selected,monkeypatch):
    settings.groq_key=SecretStr('synthetic-key')
    calls=[]
    def handler(request):
        calls.append(True)
        return limited('tokens per minute',retry='90',tokens='0')
    mock_transport(monkeypatch,handler)
    response=generation(client,headers,selected)
    Worker(database).run(once=True)
    value=client.get('/api/v1/resume-generations/'+response.json()['entity_id'],headers=headers).json()
    assert value['state']=='FAILED' and value['provider_diagnostics'][0]['retry_after_seconds']==90
    assert value['provider_diagnostics'][0]['limiting_factor']=='tokens_per_minute'
    for api in (client,TestClient(create_app(settings))):
        if api is client:
            result=generation(api,headers,selected)
        else:
            with api as restarted:result=generation(restarted,headers,selected)
        assert result.status_code==429 and result.json()['error']['code']=='PROVIDER_COOLDOWN'
        assert 0<int(result.headers['Retry-After'])<=90
    assert len(calls)==1
