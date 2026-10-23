"""Opt-in synthetic browser → live Lever → Groq → verified private PDF check."""
import argparse
import hashlib
import io
import json
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from pypdf import PdfReader

from app.core.config import ROOT
from app.schemas.ai import TailoredContent
from app.services.pdf_render import render_resume
from scripts.feasibility.common import browser_environment


def run(base_url, *, chrome=False, confirm_free_plan=False, check_restart=False):
    parsed = urlparse(base_url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
            or parsed.username or parsed.password or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment):
        raise ValueError('Only a plain loopback HTTP origin is allowed')
    if not check_restart and not confirm_free_plan:
        raise ValueError('Live Groq calls require --confirm-free-plan (no paid billing)')
    output = ROOT / 'data' / 'phase4'
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    report_path = output / 'live-studio.json'
    origin = base_url.rstrip('/')
    browser_environment()
    if not check_restart:
        from uuid import uuid4
        facts = [{'id': str(uuid4()), 'kind': kind, 'text': text} for kind, text in [
            ('name', 'Synthetic Candidate'), ('email', 'candidate@example.invalid'),
            ('skills', 'Python, FastAPI, SQL, Git'),
            ('projects', 'Built a synthetic task API using FastAPI and SQL.'),
            ('education', 'Synthetic University, Computer Science, 2024-2026')]]
        pdf, _ = render_resume(facts, TailoredContent(claims=[], changes=[],
                              selected_section_order=['skills', 'projects', 'education']))
        (output / 'synthetic-input.pdf').write_bytes(pdf)
    report = json.loads(report_path.read_text()) if check_restart else {
        'observed_at': datetime.now(timezone.utc).isoformat(), 'status': 'IN_PROGRESS',
        'candidate_data': 'synthetic only', 'applications_submitted': 0, 'employer_pages_opened': False}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**({'channel': 'chrome'} if chrome else {}))
        context = browser.new_context(viewport={'width': 1440, 'height': 1100}, reduced_motion='reduce')
        page = context.new_page()
        page.set_default_timeout(15000)
        errors = []
        page.on('pageerror', lambda _: errors.append('JAVASCRIPT_ERROR'))
        page.goto(origin + '/#studio')
        expect(page.locator('#connection')).to_have_text('Local session')
        report.update(browser='Google Chrome' if chrome else 'Chromium', browser_version=browser.version)

        def read(path):
            return page.evaluate('async path => {const r=await fetch(path); if(!r.ok) throw Error("READ_FAILED");return r.json();}', path)

        def finish():
            report['javascript_errors'] = len(errors)
            report_path.write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report, indent=2), flush=True)
            context.close()
            browser.close()
            return report

        if not check_restart:
            page.locator('nav a[data-view=explore]').click()
            with page.expect_response(lambda r: r.request.method == 'POST' and urlparse(r.url).path.endswith('/refresh')) as pending:
                page.locator('#explore .refresh-button').click()
            reference = pending.value.json()
            expect(page.locator('#notice')).to_contain_text('Refresh complete', timeout=120000)
            task = read(reference['status_url'])
            assert task['status'] == 'SUCCEEDED' and task['result']['data_origin'] == 'live'
            report.update(source_origin='live', listing_count=task['result']['listing_count'])
            page.locator('nav a[data-view=studio]').click()
            page.locator('#resume-file').set_input_files(str(output / 'synthetic-input.pdf'))
            page.locator('#upload-resume').click()
            expect(page.locator('#profile-status')).to_have_text('Needs review', timeout=30000)
            previous_profile = page.locator('#profile-version').input_value()
            page.get_by_label(re.compile('Skills ·')).first.fill('Python, FastAPI, SQL, Git, TypeScript')
            page.locator('#save-profile').click()
            expect(page.locator('#profile-version')).not_to_have_value(previous_profile)
            page.locator('#confirm-profile').click()
            expect(page.locator('#profile-status')).to_have_text('Confirmed')
            page.get_by_label('Preferred job title', exact=True).fill('Software Engineer Intern')
            page.get_by_label('Location (optional)', exact=True).fill('India')
            page.locator('#find-matches').click()
            page.wait_for_function('''() => document.querySelectorAll('.studio-match-card').length > 0
                || document.querySelector('#match-results')?.textContent.includes('No matching stored jobs')''', timeout=20000)
            matches = page.locator('.studio-match-card').count()
            report['matching_jobs'] = matches
            if not matches:
                report.update(status='BLOCKED', blocker='NO_MATCHING_LIVE_JOBS')
                return finish()
            page.get_by_role('button', name='Analyse this job', exact=True).first.click()
            expect(page.locator('#job-analysis')).to_be_visible(timeout=20000)
            page.screenshot(path=str(output / 'live-analysis-desktop.png'))
            page.locator('#groq-consent').check()
            with page.expect_response(lambda r: r.request.method == 'POST' and urlparse(r.url).path == '/api/v1/resume-generations') as pending:
                page.locator('#generate-resume').click()
            reference = pending.value.json()
            report['generation_id'] = reference['entity_id']
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                task = read(reference['status_url'])
                if task['status'] in ('SUCCEEDED', 'FAILED', 'CANCELLED'):
                    break
                page.wait_for_timeout(500)
            if task['status'] != 'SUCCEEDED':
                report.update(status='BLOCKED', blocker=task.get('error_code') or 'TASK_TIMEOUT')
                page.screenshot(path=str(output / 'live-generation-blocked.png'))
                return finish()

        generation = read('/api/v1/resume-generations/' + report['generation_id'])
        assert generation['state'] == 'VERIFIED' and generation['content']['provider'] == 'groq'
        expect(page.locator('#generation-result')).to_contain_text('Verification passed', timeout=20000)
        page.wait_for_function('() => document.querySelector("#generation-result img")?.naturalWidth > 0')
        with page.expect_download() as pending:
            page.get_by_role('link', name='Download tailored PDF', exact=True).click()
        pdf_path = output / 'live-tailored.pdf'
        pending.value.save_as(pdf_path)
        pdf = pdf_path.read_bytes()
        digest = hashlib.sha256(pdf).hexdigest()
        assert digest == generation['pdf_sha256']
        if check_restart:
            assert digest == report['pdf_sha256']
        text = '\n'.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)
        assert all(value in text for value in ('Synthetic Candidate', 'candidate@example.invalid', 'TypeScript', '2024-2026'))
        for width, height in [(1440, 1100), (375, 812)]:
            page.set_viewport_size({'width': width, 'height': height})
            page.locator('#generation-result').scroll_into_view_if_needed()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(output / f'live-studio-{width}.png'))
        page.reload()
        expect(page.locator('#generation-result')).to_contain_text('Verification passed', timeout=15000)
        same = read('/api/v1/resume-generations/' + report['generation_id'])
        assert same['resume_version_id'] == generation['resume_version_id']
        assert not errors
        content = generation['content']
        report.update(status='PASS', provider='groq', model=content['model'], pdf_sha256=digest,
            profile_version_id=generation['profile_version_id'], analysis_id=generation['analysis_id'],
            resume_version_id=generation['resume_version_id'], pdf_checks=content['pdf_checks'],
            repair_count=content['repair_count'], reverted_bullets=len(content['reverted_item_ids']),
            required_coverage=content['original_assessment']['coverage'],
            coverage_unchanged=content['original_assessment'] == content['tailored_assessment'],
            browser_reload='PASS', browser_to_pdf='PASS')
        if check_restart:
            report['backend_restart'] = 'PASS'
        return finish()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--chrome', action='store_true')
    parser.add_argument('--confirm-free-plan', action='store_true')
    parser.add_argument('--check-restart', action='store_true', help='Read existing result only; makes no AI calls')
    args = parser.parse_args()
    outcome = run(**vars(args))
    raise SystemExit(0 if outcome['status'] == 'PASS' else 1)
