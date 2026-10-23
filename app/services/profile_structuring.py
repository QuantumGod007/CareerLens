"""Ground model-selected sections in exact PDF text; contact extraction stays local."""
import json
import re
from uuid import uuid5

from app.core.errors import DomainError
from app.schemas.ai import SourcedFact, SourceSpan
from app.schemas.profile_ai import GroqProfileDraft
from app.services.profile_parser import draft_from_facts, verify_span

CONSENT = 'groq-profile-v1'
PROMPT_VERSION = 'profile-spans-v1'
CONTACT = {'name','email','phone','links'}


def model_input(pages, local, artifact_id):
    masked = {page['page']:list(page['text']) for page in pages}
    ranges = {page['page']:[] for page in pages}
    for fact in local.facts:
        if fact.kind in CONTACT:
            source = fact.source_ref
            ranges[source.page].append((source.start_offset,source.end_offset))
    names = [str(f.value) for f in local.facts if f.kind=='name']
    for page in pages:
        text = page['text']
        patterns = [r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', r'https?://\S+|www\.\S+|(?:linkedin|github)\.com/\S+']
        patterns += [re.escape(name) for name in names]
        for pattern in patterns:
            ranges[page['page']].extend(match.span() for match in re.finditer(pattern,text,re.I))
        for match in re.finditer(r'(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)',text):
            if sum(c.isdigit() for c in match.group())>=10:
                ranges[page['page']].append(match.span())
        for start,end in ranges[page['page']]:
            for index in range(start,end):
                if masked[page['page']][index] not in '\r\n':
                    masked[page['page']][index]=' '
    payload={'source_artifact_id':str(artifact_id),'offset_units':'Unicode code points; newlines count',
             'pages':[{'page':page['page'],'text':''.join(masked[page['page']])} for page in pages]}
    payload['source_candidates']=[{'page':f.source_ref.page,'start_offset':f.source_ref.start_offset,
                                  'end_offset':f.source_ref.end_offset,
                                  'source_text':''.join(masked[f.source_ref.page][f.source_ref.start_offset:f.source_ref.end_offset])}
                                 for f in local.facts if f.kind not in CONTACT]
    if len(json.dumps(payload,ensure_ascii=False))>18000:
        raise DomainError('PROFILE_AI_INPUT_LIMIT','Extracted text exceeds the AI limit; local extraction is retained without truncation.',422)
    return payload


def grounded_profile(pages, local, response, namespace, payload):
    visible={page['page']:page['text'] for page in payload['pages']}
    covered={page['page']:[] for page in pages}
    facts=[];methods={}
    for proposed in response.facts:
        source=proposed.source_ref
        if (not verify_span(pages,source) or not source.source_text.strip() or len(source.source_text)>4000
                or source.page not in visible or visible[source.page][source.start_offset:source.end_offset]!=source.source_text):
            raise DomainError('PROFILE_AI_SOURCE_INVALID','AI facts did not match exact visible PDF evidence; local extraction is retained.',422)
        if any(source.start_offset<end and source.end_offset>start for start,end in covered[source.page]):
            raise DomainError('PROFILE_AI_SOURCE_INVALID','Overlapping model evidence needs manual review; local extraction is retained.',422)
        page_text=next(page['text'] for page in pages if page['page']==source.page)
        prefix=re.split(r'[\n.;|]',page_text[:source.start_offset])[-1][-60:]
        suffix=re.split(r'[\n.;|]',page_text[source.end_offset:])[0][:60]
        qualifiers=r'\b(?:no|not|never|without|lack|learning|beginner|basic|assisted|pursuing|expected|in progress|under supervision)\b'
        if re.search(qualifiers,prefix,re.I) or re.search(qualifiers,suffix,re.I):
            raise DomainError('PROFILE_AI_SOURCE_INVALID','A selected span omitted surrounding qualification context; local extraction is retained.',422)
        covered[source.page].append((source.start_offset,source.end_offset))
        identifier=uuid5(namespace,f'groq:{source.page}:{source.start_offset}:{source.end_offset}:{proposed.kind}')
        facts.append(SourcedFact(id=identifier,kind=proposed.kind,value=source.source_text,source_ref=source))
        methods[str(identifier)]='groq'
    # Preserve every uncovered original qualification and all local contact facts.
    for original in local.facts:
        source=original.source_ref
        segments=[(source.start_offset,source.end_offset)]
        if original.kind not in CONTACT:
            for start,end in sorted(covered[source.page]):
                segments=[piece for left,right in segments for piece in
                          ((left,min(right,start)),(max(left,end),right)) if piece[0]<piece[1]]
        for start,end in segments:
            text=next(page['text'] for page in pages if page['page']==source.page)[start:end]
            start+=len(text)-len(text.lstrip());text=text.strip()
            if not text:continue
            span=SourceSpan(page=source.page,start_offset=start,end_offset=start+len(text),source_text=text)
            identifier=uuid5(namespace,f'local:{source.page}:{start}:{span.end_offset}:{original.kind}')
            facts.append(SourcedFact(id=identifier,kind=original.kind,value=text,source_ref=span))
            methods[str(identifier)]='local'
    facts.sort(key=lambda f:(f.source_ref.page,f.source_ref.start_offset,f.source_ref.end_offset))
    if len(facts)>200:
        raise DomainError('PROFILE_AI_SOURCE_INVALID','The model created too many fragments; local extraction is retained.',422)
    draft=draft_from_facts(facts,[*local.warnings,'Groq assigned sections using exact PDF spans. Review ambiguous columns, wrapped text and every fact before confirming.'])
    return draft,methods


def structure_profile(worker,task,pages,local,artifact_id,namespace):
    from app.adapters.groq_resume import GroqResumeProvider, MODEL
    from app.adapters.groq_limits import check_cooldown
    from app.persistence.models import Task
    db,queue=worker.db,worker.queue
    requested=task.input_json.get('parsing_mode','local')
    info={'requested_mode':requested,'mode':'local','provider':None,'model':None,'error_code':None,
          'consent_version':None,'prompt_version':None,'schema_version':'profile-v1'}
    methods={str(f.id):'local' for f in local.facts}
    if requested!='groq':return local,methods,info
    state=task.input_json.get('ai',{})
    provider=worker.provider or GroqResumeProvider(db.settings)
    def save(stage):
        with db.write() as session:
            current=queue.owned(session,task.id)
            current.input_json={**current.input_json,'ai':stage}
    try:
        if task.input_json.get('consent_version')!=CONSENT or not task.input_json.get('consent_at'):
            raise DomainError('AI_CONSENT_REQUIRED','Groq profile structuring requires explicit consent.',400)
        info['consent_version']=CONSENT
        if state.get('phase')=='SENDING':
            raise DomainError('PROVIDER_OUTCOME_UNKNOWN','An interrupted profile model call is not replayed.',409)
        if state.get('phase')=='LOCAL_FALLBACK':
            raise DomainError(state.get('error_code','PROFILE_AI_UNAVAILABLE'),'Local-only extraction retained.',422)
        payload=model_input(pages,local,artifact_id)
        if state.get('phase')=='STORED':
            response=GroqProfileDraft.model_validate_json(json.dumps(state['result']))
        else:
            with db.read() as session:check_cooldown(session)
            state={'phase':'SENDING','calls':1,'fallback_used':False}
            save(state)
            def before_fallback(report):
                state.update(calls=2,fallback_used=True,diagnostics=[report])
                save(state)
            if isinstance(provider,GroqResumeProvider):provider.before_fallback=before_fallback
            queue.progress(task.id,'GROQ_STRUCTURING_PROFILE',65)
            response=provider.complete(GroqProfileDraft,payload,'PROFILE')
        draft,methods=grounded_profile(pages,local,response,namespace,payload)
        state={**state,'phase':'STORED','result':response.model_dump(mode='json'),
               'model':state.get('model',getattr(provider,'model',MODEL)),
               'provider':state.get('provider',provider.provider_name),
               'diagnostics':getattr(provider,'diagnostics',[]) or state.get('diagnostics',[])}
        save(state)
        info.update(mode='groq',model=state['model'],provider=state['provider'],
                    prompt_version=PROMPT_VERSION,schema_version='profile-spans-v1')
        return draft,methods,info
    except DomainError as error:
        reports=getattr(provider,'diagnostics',[]) or state.get('diagnostics',[])
        deadlines=[r['retry_not_before'] for r in reports if r.get('http_status')==429 and r.get('retry_not_before')]
        state={**state,'phase':'LOCAL_FALLBACK','error_code':error.code,'diagnostics':reports}
        if deadlines:state['retry_not_before']=max(deadlines)
        save(state)
        info.update(mode='local_fallback',error_code=error.code)
        local=local.model_copy(update={'warnings':[*local.warnings,
            f'Local-only extraction: Groq structuring was unavailable or failed source validation ({error.code}). No model facts were accepted. Review and confirm local facts.']})
        queue.progress(task.id,'LOCAL_ONLY_PROFILE_REVIEW',75)
        return local,methods,info
