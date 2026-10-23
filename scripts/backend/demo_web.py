"""Opt-in browser → API → separate worker → live Lever verification (no employer forms)."""
import argparse
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

from app.core.config import ROOT
from scripts.feasibility.common import browser_environment


def run(base_url='http://127.0.0.1:8000', *, chrome=False):
    parsed = urlparse(base_url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost')
            or parsed.username or parsed.password or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
        raise ValueError('Only a plain loopback HTTP origin is allowed')
    origin = base_url.rstrip('/')
    output = ROOT / 'data' / 'phase3'
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    browser_environment()
    observations, commands, errors = [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**({'channel': 'chrome'} if chrome else {}))
        context = browser.new_context(viewport={'width': 1440, 'height': 1100}, reduced_motion='reduce')
        page = context.new_page()
        page.set_default_timeout(10000)
        page.on('pageerror', lambda _: errors.append('JAVASCRIPT_ERROR'))

        def observe(response):
            path = urlparse(response.url).path
            if response.request.method == 'POST' and path.endswith('/refresh'):
                commands.append(response.status)
            if re.fullmatch(r'/api/v1/tasks/[0-9a-f-]{36}', path) and response.status == 200:
                value = response.json()
                observations.append({'status': value['status'], 'progress': value['progress'], 'attempts': value['attempts']})

        page.on('response', observe)
        page.goto(origin)
        expect(page.locator('#connection')).to_have_text('Local session')
        expect(page.locator('#system-status')).to_contain_text('Ready to refresh')
        expect(page.locator('#source-summary .refresh-button')).to_be_enabled()
        page.screenshot(path=str(output / 'live-overview-desktop.png'), full_page=True)
        page.locator('nav a[data-view=explore]').click()
        with page.expect_response(lambda response: response.request.method == 'POST' and urlparse(response.url).path.endswith('/refresh')) as pending:
            page.locator('#explore .refresh-button').click()
        response = pending.value
        assert response.status == 202
        reference = response.json()
        expect(page.locator('#notice')).to_contain_text('Refresh complete', timeout=120000)
        task = page.evaluate("async id => (await fetch('/api/v1/tasks/' + id)).json()", reference['task_id'])
        assert task['status'] == 'SUCCEEDED' and task['result']['data_origin'] == 'live'
        assert task['result']['listing_count'] > 0
        expect(page.locator('.job-card')).to_have_count(min(12, task['result']['listing_count']))
        page.screenshot(path=str(output / 'live-jobs-desktop.png'), full_page=True)
        page.locator('nav a[data-view=activity]').click()
        expect(page.locator('#task-detail .timeline')).to_contain_text('Succeeded')
        page.screenshot(path=str(output / 'live-activity-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 375, 'height': 812})
        page.locator('nav a[data-view=explore]').click()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(output / 'live-jobs-mobile.png'), full_page=True)
        page.locator('.job-card h3 button').first.click()
        expect(page.get_by_role('dialog')).to_be_visible()
        expect(page.get_by_role('link', name='View on employer website', exact=False)).to_have_attribute('rel', 'noopener noreferrer')
        page.screenshot(path=str(output / 'live-details-mobile.png'))
        page.keyboard.press('Escape')
        page.reload()
        expect(page.locator('#connection')).to_have_text('Local session')
        expect(page.locator('#results-count')).to_contain_text('stored')
        assert page.evaluate('Object.keys(localStorage).length + Object.keys(sessionStorage).length') == 0
        assert commands == [202] and not errors
        report = {'observed_at': datetime.now(timezone.utc).isoformat(), 'status': 'PASS',
            'browser': 'Google Chrome' if chrome else 'Chromium', 'browser_version': browser.version,
            'flow': 'browser → FastAPI → SQLite → separate worker → live Lever → stored jobs → browser',
            'task_id': reference['task_id'], 'task_status': task['status'], 'data_origin': task['result']['data_origin'],
            'listing_count': task['result']['listing_count'], 'refresh_commands': len(commands), 'observed_task_states': observations,
            'desktop': [1440, 1100], 'mobile': [375, 812], 'session_reload': 'PASS', 'horizontal_overflow': False,
            'javascript_errors': len(errors), 'employer_pages_opened': False, 'applications_submitted': 0}
        context.close()
        browser.close()
    (output / 'live-browser.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:8000')
    parser.add_argument('--chrome', action='store_true', help='Use installed Google Chrome in an isolated context')
    args = parser.parse_args()
    run(args.base_url, chrome=args.chrome)
