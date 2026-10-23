import json

import groq
import httpx
import pytest
from pydantic import SecretStr

from app.adapters.groq_resume import GroqResumeProvider, MODEL
from app.core.errors import DomainError
from app.schemas.ai import VerificationResult


@pytest.mark.parametrize('case,expected',[
    ('valid',None),('schema','SCHEMA_INVALID'),('incomplete','INCOMPLETE_MODEL_OUTPUT'),
    ('model','MODEL_UNAVAILABLE'),('401','AUTHENTICATION_FAILED'),('403','PROVIDER_ACCESS_DENIED'),
    ('404','MODEL_UNAVAILABLE'),('429','RATE_LIMIT_OR_QUOTA_EXHAUSTED'),('timeout','PROVIDER_TIMEOUT'),
    ('network','PROVIDER_NETWORK_ERROR'),('500','PROVIDER_UNAVAILABLE'),
])
def test_typed_groq_sdk_errors_and_fixed_no_retry_boundary(settings,monkeypatch,case,expected,caplog):
    settings.groq_key=SecretStr('SYNTHETIC_PRIVATE_PROVIDER_KEY')
    real_client=groq.Groq
    calls=[]
    def transport(request):
        payload=json.loads(request.content);calls.append(payload)
        assert payload['model']==MODEL and payload['response_format']['type']=='json_schema'
        assert payload['response_format']['json_schema']['strict'] is True
        if case=='timeout':raise httpx.ReadTimeout('SYNTHETIC_PRIVATE_EXCEPTION',request=request)
        if case=='network':raise httpx.ConnectError('SYNTHETIC_PRIVATE_EXCEPTION',request=request)
        if case.isdigit():return httpx.Response(int(case),json={'error':{'message':'SYNTHETIC_PRIVATE_EXCEPTION'}})
        content=json.dumps({'pass':True,'violations':[],'uncertain_claims':[]}) if case!='schema' else '{"invalid":true}'
        return httpx.Response(200,json={'id':'synthetic','object':'chat.completion','created':1,
            'model':'unapproved-model' if case=='model' else MODEL,
            'choices':[{'index':0,'message':{'role':'assistant','content':content},'finish_reason':'length' if case=='incomplete' else 'stop'}]})
    def factory(**kwargs):
        assert kwargs['max_retries']==0 and kwargs['base_url']=='https://api.groq.com' and kwargs['timeout']==35
        return real_client(**kwargs,http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    monkeypatch.setattr('app.adapters.groq_resume.groq.Groq',factory)
    provider=GroqResumeProvider(settings)
    if expected:
        with pytest.raises(DomainError) as error:provider.complete(VerificationResult,{'synthetic':'data'},'VERIFY')
        assert error.value.code==expected
    else:assert provider.complete(VerificationResult,{'synthetic':'data'},'VERIFY').passed
    assert len(calls)==1
    assert 'SYNTHETIC_PRIVATE_PROVIDER_KEY' not in caplog.text and 'SYNTHETIC_PRIVATE_EXCEPTION' not in caplog.text


def test_missing_key_and_input_limit_do_not_create_client(settings,monkeypatch):
    def forbidden(**kwargs):raise AssertionError('No client should be created')
    monkeypatch.setattr('app.adapters.groq_resume.groq.Groq',forbidden)
    with pytest.raises(DomainError,match='MISSING_API_KEY'):GroqResumeProvider(settings).complete(VerificationResult,{},'VERIFY')
    settings.groq_key=SecretStr('synthetic-key')
    with pytest.raises(DomainError,match='AI_INPUT_LIMIT'):GroqResumeProvider(settings).complete(VerificationResult,{'data':'x'*27000},'VERIFY')
