import json
import signal

from app.schemas.ai import TailoredContent, VerificationResult

class ControlledProvider:
    provider_name='controlled_fixture'
    def __init__(self, mutation=None):
        self.calls=[];self.mutation=mutation
    def complete(self,schema,payload,purpose):
        self.calls.append((purpose,payload))
        if schema is VerificationResult:
            return VerificationResult.model_validate({'pass':True,'violations':[],'uncertain_claims':[]})
        fact=next(f for f in payload['facts'] if f['section']=='projects')
        revised=fact['text'].replace('Built','Developed',1)
        claim={'item_id':fact['id'],'section':fact['section'],'text':revised,'source_fact_ids':[fact['id']]}
        change={**claim,'before':fact['text'],'after':revised,'reason':'Clarify the existing implementation wording.'}
        change.pop('text')
        value={'claims':[claim],'changes':[change],'selected_section_order':payload['sections']}
        if self.mutation:self.mutation(value)
        return TailoredContent.model_validate_json(json.dumps(value))


def run_worker(settings):
    from app.core.config import Settings
    from app.persistence.database import Database
    from app.worker import Worker
    database=Database(Settings.model_validate(settings))
    worker=Worker(database,provider=ControlledProvider())
    for signum in (signal.SIGTERM,signal.SIGINT):
        signal.signal(signum,lambda *_:worker.stop_event.set())
    try:
        worker.run()
    finally:
        database.close()
