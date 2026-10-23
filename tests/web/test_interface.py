import json
import socket
import threading
import time
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from app.core.config import ROOT
from app.main import create_app
from app.tools.init_db import BOARD_ID
from scripts.feasibility.common import browser_environment

TIME = '2026-10-23T09:00:00Z'
TASK_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'


@pytest.fixture(scope='session')
def chromium():
    browser_environment()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def web_server(database, settings):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    local = settings.model_copy(update={'allowed_origins': (origin,)})
    server = uvicorn.Server(uvicorn.Config(create_app(local), log_level='error', access_log=False, proxy_headers=False))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(.02)
    assert server.started
    yield origin
    server.should_exit = True
    thread.join(timeout=5)
    listener.close()
    assert not thread.is_alive()


def job(index, title=None):
    identifier = str(UUID(int=index + 1))
    return {'id': identifier, 'external_id': identifier, 'canonical_job_key': f'lever:drivetrain:{identifier}',
        'title': title or f'Engineering opportunity {index:02}', 'employer': 'Drivetrain',
        'location': 'Bengaluru' if index % 2 else 'Mumbai', 'employment_type': 'Internship' if index % 2 else 'Full-time',
        'source_url': f'https://jobs.lever.co/drivetrain/{identifier}',
        'apply_url': f'https://jobs.lever.co/drivetrain/{identifier}/apply', 'fetched_at': TIME, 'content_hash': 'a' * 64}


class Harness:
    """Explicit synthetic API fixtures. The frontend and pairing endpoint are real."""
    def __init__(self, page, origin):
        self.page, self.origin = page, origin
        self.jobs = [job(index) for index in range(25)]
        self.worker_ready = True
        self.health_error = False
        self.jobs_error = None
        self.incomplete = False
        self.refresh_error = None
        self.drop_first = False
        self.posts = []
        self.status = 'QUEUED'
        self.task_gets = 0
        self.page.route('**/health', self.health)
        self.page.route('**/api/v1/source-boards**', self.sources)
        self.page.route('**/api/v1/tasks/**', self.tasks)

    def reply(self, route, value, status=200):
        route.fulfill(status=status, content_type='application/json', body=json.dumps(value))

    def error(self, route, code, status):
        self.reply(route, {'error': {'code': code, 'message': 'Safe fixture error', 'retryable': False, 'details': {}},
                           'correlation_id': TASK_ID}, status)

    def health(self, route):
        if self.health_error:
            route.abort()
        else:
            self.reply(route, {'version': '0.3.0', 'api_ready': True, 'database_ready': True, 'ready': self.worker_ready,
                'worker': {'ready': self.worker_ready, 'heartbeat_at': TIME, 'lease_expires_at': TIME},
                'groq_key_present': False, 'groq_model': 'openai/gpt-oss-120b', 'fallback_enabled': False})

    def sources(self, route):
        parsed = urlparse(route.request.url)
        if parsed.path.endswith('/refresh'):
            self.posts.append({'key': route.request.headers.get('idempotency-key'), 'body': route.request.post_data_json})
            if self.refresh_error:
                return self.error(route, 'STALE_REVISION', self.refresh_error)
            if self.drop_first and len(self.posts) == 1:
                return route.abort()
            self.reply(route, {'task_id': TASK_ID, 'entity_type': 'source_board', 'entity_id': str(BOARD_ID),
                               'status_url': f'/api/v1/tasks/{TASK_ID}'}, 202)
        elif parsed.path.endswith('/jobs'):
            if self.jobs_error:
                return self.error(route, 'LOCAL_SESSION_REQUIRED' if self.jobs_error == 401 else 'INTERNAL_ERROR', self.jobs_error)
            if self.incomplete:
                return self.reply(route, {'items': [{}], 'total': 'invalid'})
            query = parse_qs(parsed.query)
            offset, limit = int(query.get('offset', [0])[0]), int(query.get('limit', [12])[0])
            self.reply(route, {'items': self.jobs[offset:offset+limit], 'total': len(self.jobs),
                'offset': offset, 'limit': limit, 'last_refreshed_at': TIME})
        else:
            self.reply(route, [{'id': str(BOARD_ID), 'family': 'lever', 'slug': 'drivetrain', 'employer': 'Drivetrain',
                'enabled': True, 'revision': 1, 'validated_at': TIME, 'refreshed_at': TIME, 'last_error_code': None}])

    def tasks(self, route):
        if route.request.url.endswith('/events'):
            self.reply(route, [{'id': TASK_ID, 'kind': self.status, 'correlation_id': TASK_ID, 'created_at': TIME, 'metadata': {}}])
            return
        self.task_gets += 1
        self.reply(route, {'id': TASK_ID, 'correlation_id': TASK_ID, 'entity_type': 'source_board', 'entity_id': str(BOARD_ID),
            'kind': 'source_refresh', 'status': self.status, 'current_step': 'FETCHING_SOURCE',
            'progress': 100 if self.status == 'SUCCEEDED' else 10 if self.status in ('RUNNING', 'WAITING') else 0,
            'attempts': 1, 'max_attempts': 3, 'retry_eligible': self.status == 'WAITING',
            'retry_at': TIME if self.status == 'WAITING' else None, 'lease_owner': None, 'lease_expires_at': None, 'heartbeat_at': TIME,
            'error_code': 'SOURCE_HTTP_ERROR' if self.status == 'FAILED' else None,
            'result': {'entity_type': 'source_board', 'entity_id': str(BOARD_ID), 'listing_count': len(self.jobs),
                       'new_snapshots': 0, 'reused_snapshots': 0, 'duplicates_removed': 0, 'data_origin': 'fixture'} if self.status == 'SUCCEEDED' else None,
            'created_at': TIME, 'updated_at': TIME, 'finished_at': TIME if self.status in ('SUCCEEDED', 'FAILED', 'CANCELLED') else None})

    def open(self, view='overview'):
        self.page.goto(f'{self.origin}/#{view}')
        self.page.locator('#connection').get_by_text('Local session', exact=True).wait_for()
        expect(self.page.locator('#results-count')).to_contain_text('12 shown') if self.jobs else None


@pytest.fixture
def ui(chromium, web_server):
    context = chromium.new_context(viewport={'width': 1440, 'height': 1100}, reduced_motion='reduce')
    page = context.new_page()
    page.set_default_timeout(7000)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    harness = Harness(page, web_server)
    yield harness
    context.close()
    assert not errors, errors


from playwright.sync_api import expect
import pytest

from app.core.config import ROOT


def test_load_navigation_cookie_reload_and_disconnect(ui):
    ui.open()
    page = ui.page
    expect(page.locator('#overview-title')).to_be_visible()
    expect(page.locator('#system-status')).to_contain_text('Ready to refresh')
    expect(page.locator('#source-summary')).to_contain_text('25')
    page.get_by_role('link', name='Explore jobs', exact=False).click()
    expect(page.locator('#explore-title')).to_be_focused()
    expect(page.locator('.job-card')).to_have_count(12)
    page.get_by_role('link', name='Activity', exact=True).click()
    expect(page.locator('#activity-title')).to_be_visible()
    cookie = next(c for c in page.context.cookies() if c['name'] == 'careerlens_browser')
    assert cookie['httpOnly'] and cookie['sameSite'] == 'Strict'
    assert page.evaluate('document.cookie') == ''
    assert page.evaluate('Object.keys(localStorage).length + Object.keys(sessionStorage).length') == 0
    page.reload()
    expect(page.locator('#connection')).to_have_text('Local session')
    page.get_by_role('button', name='Disconnect', exact=True).click()
    expect(page.locator('#connection')).to_have_text('Disconnected')
    page.get_by_role('button', name='Connect', exact=True).click()
    expect(page.locator('#connection')).to_have_text('Local session')


def test_search_filters_incremental_pagination_and_empty(ui):
    ui.open('explore')
    page = ui.page
    page.get_by_label('Search loaded listings').fill('opportunity 03')
    expect(page.locator('.job-card')).to_have_count(1)
    page.get_by_role('button', name='Clear filters').click()
    page.get_by_label('Employment type', exact=True).select_option('Internship')
    expect(page.locator('.job-card')).to_have_count(6)
    page.get_by_label('Location', exact=True).select_option('Mumbai')
    expect(page.locator('.job-card')).to_have_count(0)
    expect(page.locator('#job-list')).to_contain_text('Nothing in this view yet')
    page.get_by_role('button', name='Clear filters').click()
    page.get_by_role('button', name='Load more listings').click()
    expect(page.locator('.job-card')).to_have_count(24)
    page.get_by_role('button', name='Load more listings').click()
    expect(page.locator('.job-card')).to_have_count(25)
    expect(page.locator('#load-more')).to_be_hidden()


def test_keyboard_dialog_focus_and_external_links(ui):
    ui.open('explore')
    page = ui.page
    title = page.get_by_role('button', name='Engineering opportunity 00', exact=True)
    title.focus()
    page.keyboard.press('Enter')
    expect(page.get_by_role('dialog')).to_be_visible()
    expect(page.get_by_role('button', name='Close job details')).to_be_focused()
    employer = page.get_by_role('link', name='View on employer website', exact=False)
    expect(employer).to_have_attribute('target', '_blank')
    expect(employer).to_have_attribute('rel', 'noopener noreferrer')
    expect(employer).to_have_attribute('href', ui.jobs[0]['source_url'])
    last = page.get_by_role('link', name='Employer application page', exact=False)
    last.focus()
    page.keyboard.press('Tab')
    expect(page.get_by_role('button', name='Close job details')).to_be_focused()
    page.keyboard.press('Escape')
    expect(page.get_by_role('dialog')).to_be_hidden()
    expect(title).to_be_focused()


def test_refresh_double_click_real_progress_wait_and_success(ui):
    ui.open('explore')
    page = ui.page
    page.locator('#explore .refresh-button').evaluate('button => {button.click(); button.click();}')
    expect(page.locator('#recent-activity')).to_contain_text('Queued')
    assert len(ui.posts) == 1
    ui.status = 'RUNNING'
    page.get_by_role('link', name='Activity', exact=True).click()
    expect(page.locator('#task-detail')).to_contain_text('Running', timeout=7000)
    expect(page.locator('#task-detail progress')).to_have_attribute('value', '10')
    ui.status = 'WAITING'
    expect(page.locator('#task-detail')).to_contain_text('Waiting for retry', timeout=7000)
    ui.jobs[0]['title'] = 'Newly refreshed opportunity'
    ui.status = 'SUCCEEDED'
    expect(page.locator('#task-detail')).to_contain_text('Succeeded', timeout=7000)
    expect(page.locator('#task-detail')).to_contain_text('Controlled fixture data')
    expect(page.locator('#task-detail .timeline')).to_contain_text('Succeeded')
    page.get_by_role('link', name='Explore jobs', exact=False).click()
    expect(page.locator('#job-list')).to_contain_text('Newly refreshed opportunity')
    expect(page.locator('#notice')).to_contain_text('Refresh complete')
    requests = ui.task_gets
    page.wait_for_timeout(2300)
    assert ui.task_gets == requests  # No polling after terminal outcome.


@pytest.mark.parametrize('status', ['FAILED', 'CANCELLED'])
def test_unsuccessful_refresh_keeps_old_listings_and_labels_them(ui, status):
    ui.open('explore')
    page = ui.page
    page.locator('#explore .refresh-button').click()
    expect(page.locator('#recent-activity')).to_contain_text('Queued')
    ui.status = status
    expect(page.locator('#notice')).to_contain_text('Refresh failed' if status == 'FAILED' else 'Refresh cancelled', timeout=7000)
    expect(page.locator('.job-card')).to_have_count(12)
    expect(page.locator('#jobs-warning')).to_contain_text('earlier stored results')
    assert 'Refresh complete' not in page.locator('#notice').inner_text()


def test_ambiguous_refresh_reuses_exact_idempotency_request(ui):
    ui.drop_first = True
    ui.open('explore')
    page = ui.page
    page.locator('#explore .refresh-button').click()
    expect(page.locator('#notice')).to_contain_text('Cannot reach')
    ui.status = 'SUCCEEDED'  # Response lost after the synthetic command was accepted.
    page.get_by_role('button', name='Retry refresh request', exact=False).click()
    expect(page.locator('#notice')).to_contain_text('Refresh complete')
    assert len(ui.posts) == 2 and ui.posts[0] == ui.posts[1]


def test_worker_offline_and_health_unknown_are_truthful(ui):
    ui.worker_ready = False
    ui.open()
    page = ui.page
    expect(page.locator('#system-status')).to_contain_text('Stopped · start CareerLens')
    expect(page.locator('#source-summary .refresh-button')).to_be_disabled()
    assert 'worker is stopped' in page.locator('#source-summary .refresh-button').get_attribute('title')
    ui.health_error = True
    page.reload()
    expect(page.locator('#system-status')).to_contain_text('Unknown')
    expect(page.locator('#notice')).to_contain_text('Cannot reach')


def test_unavailable_backend_connection_and_invalid_session(ui):
    page = ui.page
    page.route('**/api/v1/browser-session', lambda route: route.abort())
    page.goto(ui.origin)
    expect(page.locator('#connection')).to_have_text('Disconnected')
    expect(page.locator('#notice')).to_contain_text('Cannot reach')
    page.unroute('**/api/v1/browser-session')
    page.get_by_role('button', name='Connect', exact=True).click()
    expect(page.locator('#connection')).to_have_text('Local session')
    page.get_by_role('link', name='Explore jobs', exact=False).click()
    ui.jobs_error = 401
    page.get_by_role('button', name='Load more listings').click()
    expect(page.locator('#connection')).to_have_text('Disconnected')
    expect(page.locator('#notice')).to_contain_text('needs reconnecting')
    ui.jobs_error = None
    page.get_by_role('button', name='Connect', exact=True).click()
    expect(page.locator('#connection')).to_have_text('Local session')


@pytest.mark.parametrize('failure', [403, 409, 500, 'incomplete'])
def test_errors_are_distinct_and_do_not_erase_loaded_jobs(ui, failure):
    ui.open('explore')
    page = ui.page
    if failure == 'incomplete':
        ui.incomplete = True
    else:
        ui.jobs_error = failure
    page.get_by_role('button', name='Load more listings').click()
    expected = {403: 'security boundary', 409: 'conflicts with an earlier action', 500: 'could not complete', 'incomplete': 'incomplete response'}[failure]
    expect(page.locator('#notice')).to_contain_text(expected)
    expect(page.locator('.job-card')).to_have_count(12)
    expect(page.get_by_role('button', name='Retry loading listings')).to_be_visible()


def test_empty_source_and_no_unsafe_job_markup_or_links(ui):
    ui.jobs[0]['title'] = '<img src=x onerror="window.injected=true">'
    ui.jobs[0]['source_url'] = 'javascript:window.injected=true'
    ui.jobs[0]['apply_url'] = 'https://evil.example/apply'
    ui.open('explore')
    page = ui.page
    expect(page.locator('#job-list')).to_contain_text('<img src=x')
    assert page.locator('#job-list img').count() == 0
    page.get_by_role('button', name=ui.jobs[0]['title'], exact=True).click()
    expect(page.get_by_role('dialog')).to_contain_text('destination could not be verified')
    assert page.locator('#job-detail a').count() == 0
    assert page.evaluate('window.injected || false') is False
    page.keyboard.press('Escape')
    ui.jobs = []
    page.reload()
    expect(page.locator('#job-list')).to_contain_text('A clean slate')
    expect(page.locator('#results-count')).to_contain_text('0 stored')


def test_task_lookup_validation_and_actual_events(ui):
    ui.open('activity')
    page = ui.page
    page.get_by_label('Look up a task ID').fill('invalid')
    page.get_by_role('button', name='Look up', exact=True).click()
    expect(page.locator('#notice')).to_contain_text('valid task UUID')
    ui.status = 'SUCCEEDED'
    page.get_by_label('Look up a task ID').fill(TASK_ID)
    page.get_by_role('button', name='Look up', exact=True).click()
    expect(page.locator('#task-detail .timeline')).to_contain_text('Succeeded')
    expect(page.locator('#task-detail')).to_contain_text(TASK_ID)


def test_accessible_loading_state_resolves_to_stored_listings(ui):
    pending = []
    ui.page.route('**/api/v1/source-boards/*/jobs?*', lambda route: pending.append(route))
    ui.page.goto(f'{ui.origin}/#explore')
    expect(ui.page.locator('#job-list')).to_have_attribute('aria-busy', 'true')
    expect(ui.page.locator('#job-list')).to_contain_text('Loading stored listings')
    assert len(pending) == 1
    ui.sources(pending[0])
    expect(ui.page.locator('.job-card')).to_have_count(12)
    expect(ui.page.locator('#job-list')).to_have_attribute('aria-busy', 'false')


def test_refresh_conflict_reloads_before_explicit_new_command(ui):
    ui.refresh_error = 409
    ui.open('explore')
    page = ui.page
    page.locator('#explore .refresh-button').click()
    expect(page.locator('#notice')).to_contain_text('conflicts with an earlier action')
    page.locator('#notice-retry').click()
    expect(page.locator('#notice')).to_contain_text('Source reloaded')
    assert len(ui.posts) == 1
    ui.refresh_error = None
    ui.status = 'SUCCEEDED'
    page.locator('#explore .refresh-button').click()
    expect(page.locator('#notice')).to_contain_text('Refresh complete')
    assert len(ui.posts) == 2 and ui.posts[0]['key'] != ui.posts[1]['key']


def test_real_backend_rejects_invalid_token_and_cookie_and_reconnects(ui):
    ui.open('explore')
    page = ui.page
    page.unroute('**/api/v1/source-boards**')
    invalid_header = page.evaluate("async () => (await fetch('/api/v1/source-boards', {headers: {'X-CareerLens-Token': 'invalid-synthetic-token'}})).status")
    assert invalid_header == 401
    assert page.evaluate("async () => (await fetch('/api/v1/source-boards')).status") == 200
    page.context.clear_cookies()
    page.context.add_cookies([{'name': 'careerlens_browser', 'value': 'forged-synthetic-cookie',
                              'domain': '127.0.0.1', 'path': '/api/v1'}])
    assert page.evaluate("async () => (await fetch('/api/v1/source-boards')).status") == 401
    page.reload()
    expect(page.locator('#connection')).to_have_text('Local session')
    expect(page.locator('#results-count')).to_contain_text('0 stored')


def test_responsive_viewports_and_sanitized_screenshots(ui):
    ui.open()
    page = ui.page
    output = ROOT / 'data' / 'phase3'
    output.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(output / 'fixture-overview-desktop.png'), full_page=True)
    for width in [1440, 1024, 768, 375]:
        page.set_viewport_size({'width': width, 'height': 900})
        for view in ['overview', 'explore', 'activity']:
            page.locator(f'nav a[data-view={view}]').click()
            expect(page.locator(f'#{view}-title')).to_be_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), (width, view)
    page.locator('nav a[data-view=explore]').click()
    page.screenshot(path=str(output / 'fixture-jobs-mobile.png'), full_page=True)
