import io
import multiprocessing
import re
import signal
import socket
import threading
import time

import pytest
import uvicorn
from playwright.sync_api import sync_playwright,expect
from pypdf import PdfReader

from app.core.config import ROOT, identity
from app.main import create_app
from app.persistence.models import WorkerHeartbeat, ResumeGeneration
from sqlalchemy import select
from scripts.feasibility.common import browser_environment
from .helpers import run_worker
from .test_pipeline import resume_pdf,persisted_jobs


@pytest.fixture
def studio_browser():
    browser_environment()
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def studio_ui(settings,database,client,headers,studio_browser):
    persisted_jobs(client,headers,database,3)
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(128)
    origin=f'http://127.0.0.1:{listener.getsockname()[1]}'
    local=settings.model_copy(update={'allowed_origins':(origin,)})
    server=uvicorn.Server(uvicorn.Config(create_app(local),log_level='error',access_log=False,proxy_headers=False))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    worker=multiprocessing.get_context('spawn').Process(target=run_worker,args=(local.model_dump(mode='json'),))
    worker.start()
    deadline=time.monotonic()+10
    ready=False
    while time.monotonic()<deadline and worker.is_alive():
        with database.read() as session:
            heartbeat=session.get(WorkerHeartbeat,'primary')
            ready=bool(heartbeat and heartbeat.running)
        if ready and server.started:break
        time.sleep(.05)
    assert ready and server.started
    context=studio_browser.new_context(viewport={'width':1440,'height':1100},reduced_motion='reduce')
    page=context.new_page();page.set_default_timeout(12000)
    errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto(origin+'/#studio')
    expect(page.locator('#connection')).to_have_text('Local session')
    yield page,origin
    try:
        context.close()
    finally:
        if worker.is_alive():worker.terminate()
        worker.join(timeout=15)
        if worker.is_alive():worker.kill();worker.join()
        server.should_exit=True;thread.join(timeout=5);listener.close()
    assert not errors,errors
    assert not thread.is_alive() and worker.exitcode==0


def upload_and_confirm(page,resume_pdf,*,correct=False):
    page.locator('#resume-file').set_input_files({'name':'synthetic-resume.pdf','mimeType':'application/pdf','buffer':resume_pdf})
    page.locator('#upload-resume').evaluate('button => {button.click();button.click();}')
    expect(page.locator('#profile-status')).to_have_text('Needs review',timeout=20000)
    expect(page.locator('#profile-review')).to_be_visible()
    expect(page.locator('#find-matches')).to_be_disabled()
    if correct:
        page.get_by_label(re.compile('Skills ·')).first.fill('Python, FastAPI, SQL, Git, TypeScript')
        page.locator('#save-profile').click()
        expect(page.locator('#profile-version-note')).to_contain_text('Version 2',timeout=12000)
        expect(page.locator('#profile-status')).to_have_text('Needs review')
    page.locator('#confirm-profile').click()
    expect(page.locator('#profile-status')).to_have_text('Confirmed')
    expect(page.locator('#find-matches')).to_be_enabled()


def select_matching_job(page):
    page.get_by_label('Preferred job title',exact=True).fill('Software Engineer Intern')
    page.get_by_label('Location (optional)',exact=True).fill('India')
    page.locator('#find-matches').click()
    expect(page.locator('.studio-match-card')).to_have_count(2,timeout=15000)
    page.get_by_role('button',name='Analyse this job',exact=True).first.click()
    expect(page.locator('#job-analysis')).to_be_visible(timeout=15000)
    expect(page.locator('#job-analysis')).to_contain_text('66.7%')
    expect(page.locator('#job-analysis')).to_contain_text('Not evidenced')
    expect(page.locator('#generate-resume')).to_be_disabled()


@pytest.mark.parametrize('width',[1440,375])
def test_actual_browser_upload_correction_matching_generation_preview_download_reload(studio_ui,resume_pdf,database,tmp_path,width):
    page,origin=studio_ui
    page.set_viewport_size({'width':width,'height':1000 if width==1440 else 812})
    posts=[]
    page.on('request',lambda request:posts.append(request.url) if request.method=='POST' else None)
    upload_and_confirm(page,resume_pdf,correct=True)
    expect(page.locator('#profile-facts')).to_contain_text('Explicit user fact')
    select_matching_job(page)
    page.locator('#groq-consent').check()
    page.locator('#generate-resume').evaluate('button => {button.click();button.click();}')
    expect(page.locator('#generation-result')).to_contain_text('Verification passed',timeout=25000)
    expect(page.locator('#generation-result')).to_contain_text('CONTROLLED PROVIDER FIXTURE')
    expect(page.locator('#generation-result')).to_contain_text('Verified change')
    expect(page.locator('#generation-result img')).to_be_visible()
    page.wait_for_function('() => document.querySelector("#generation-result img")?.naturalWidth > 0')
    with page.expect_download() as download:
        page.get_by_role('link',name='Download tailored PDF',exact=True).click()
    path=tmp_path/'downloaded.pdf';download.value.save_as(path)
    text='\n'.join(p.extract_text() for p in PdfReader(path).pages)
    assert 'Synthetic Candidate' in text and 'candidate@example.invalid' in text and 'TypeScript' in text and '2024-2026' in text
    assert sum(url.endswith('/api/v1/profiles') for url in posts)==1
    assert sum(url.endswith('/api/v1/resume-generations') for url in posts)==1
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    output=ROOT/'data'/'phase4';output.mkdir(parents=True,exist_ok=True)
    page.locator('#generation-result').scroll_into_view_if_needed()
    page.screenshot(path=str(output/f'controlled-studio-{width}.png'))
    with database.read() as session:before=session.scalar(select(ResumeGeneration)).stage_json['calls']
    page.reload()
    expect(page.locator('#profile-status')).to_have_text('Confirmed')
    expect(page.locator('#generation-result')).to_contain_text('Verification passed',timeout=15000)
    with database.read() as session:assert session.scalar(select(ResumeGeneration)).stage_json['calls']==before
    assert page.evaluate('Object.keys(localStorage).length+Object.keys(sessionStorage).length')==0


def test_browser_pdf_validation_and_safe_error(studio_ui):
    page,_=studio_ui
    page.locator('#resume-file').set_input_files({'name':'invalid.pdf','mimeType':'application/pdf','buffer':b'%PDF-1.7\ncorrupt'})
    page.locator('#upload-resume').click()
    expect(page.locator('#studio-progress')).to_contain_text('Failed',timeout=15000)
    expect(page.locator('#studio-progress')).to_contain_text('corrupt or unreadable')
    expect(page.locator('#profile-review')).to_be_hidden()
    expect(page.locator('#find-matches')).to_be_disabled()


def test_browser_lost_generation_response_retries_same_logical_command(studio_ui,resume_pdf):
    page,_=studio_ui
    upload_and_confirm(page,resume_pdf)
    select_matching_job(page)
    keys=[]
    def intercept(route):
        if route.request.method!='POST':
            route.continue_();return
        keys.append(route.request.headers['idempotency-key'])
        if len(keys)==1:route.abort()
        else:route.continue_()
    page.route('**/api/v1/resume-generations',intercept)
    page.locator('#groq-consent').check();page.locator('#generate-resume').click()
    expect(page.locator('#notice')).to_contain_text('Cannot reach')
    page.locator('#notice-retry').click()
    expect(page.locator('#generation-result')).to_contain_text('Verification passed',timeout=25000)
    assert len(keys)==2 and keys[0]==keys[1]


def test_browser_session_expiry_upload_reconnect_and_multipart_csrf_guard(studio_ui,resume_pdf):
    page,origin=studio_ui
    status=page.evaluate("""async () => {const form=new FormData();form.append('resume',new Blob(['%PDF-test']), 'test.pdf');return (await fetch('/api/v1/profiles',{method:'POST',body:form,headers:{'Idempotency-Key':crypto.randomUUID()}})).status;}""")
    assert status==403
    page.context.clear_cookies()
    page.locator('#resume-file').set_input_files({'name':'synthetic.pdf','mimeType':'application/pdf','buffer':resume_pdf})
    page.locator('#upload-resume').click()
    expect(page.locator('#connection')).to_have_text('Disconnected')
    page.get_by_role('button',name='Connect',exact=True).click()
    expect(page.locator('#connection')).to_have_text('Local session')
    expect(page.locator('#resume-file-state')).to_have_text('No file selected.')


def test_delayed_historical_profile_response_cannot_replace_latest_corrections(studio_ui,resume_pdf):
    page,_=studio_ui
    upload_and_confirm(page,resume_pdf,correct=True)
    options=page.locator('#profile-version option').evaluate_all('(options) => options.map(o=>o.value)')
    latest,older=options[:2]
    held=[]
    page.route(f'**/api/v1/profiles/{older}',lambda route:held.append(route))
    page.locator('#profile-version').select_option(older)
    page.wait_for_timeout(150)
    assert held
    page.locator('#profile-version').select_option(latest)
    expect(page.locator('#profile-version-note')).to_contain_text('Version 2')
    held[0].fulfill(response=held[0].fetch())
    page.wait_for_timeout(150)
    expect(page.locator('#profile-version')).to_have_value(latest)
    expect(page.locator('#profile-version-note')).to_contain_text('Version 2')
    expect(page.get_by_label(re.compile('Skills ·')).first).to_have_value('Python, FastAPI, SQL, Git, TypeScript')


@pytest.mark.parametrize('code',['RATE_LIMIT_OR_QUOTA_EXHAUSTED','VERIFICATION_FAILED'])
def test_browser_generation_failure_never_exposes_a_pdf(studio_ui,resume_pdf,database,client,headers,code):
    from app.persistence.models import Task
    from uuid import UUID
    page,_=studio_ui
    upload_and_confirm(page,resume_pdf)
    select_matching_job(page)
    def reject(route):
        if route.request.method!='POST':
            route.continue_();return
        from .test_pipeline import send
        response=send(client,headers,'/api/v1/resume-generations',route.request.post_data_json)
        assert response.status_code==202
        reference=response.json()
        with database.write() as session:
            task=session.get(Task,UUID(reference['task_id']))
            task.status='FAILED';task.error_code=code;task.current_step='PROCESSING_ERROR'
            generation=session.get(ResumeGeneration,UUID(reference['entity_id']))
            generation.state='BLOCKED' if code=='VERIFICATION_FAILED' else 'FAILED'
            generation.error_code=code
        route.fulfill(status=202,json=reference)
    page.route('**/api/v1/resume-generations',reject)
    page.locator('#groq-consent').check();page.locator('#generate-resume').click()
    expect(page.locator('#generation-result')).to_contain_text('rate limited' if code.startswith('RATE') else 'blocked this document',timeout=15000)
    expect(page.get_by_role('link',name='Download tailored PDF',exact=True)).to_have_count(0)
    expect(page.locator('#generation-result img')).to_have_count(0)
