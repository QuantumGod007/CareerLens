from fastapi.testclient import TestClient
import pytest

from app.core.config import identity
from app.core.security import COOKIE
from app.main import create_app
from app.tools.init_db import BOARD_ID

ORIGIN = 'http://127.0.0.1:8000'
BROWSER = {'Origin': ORIGIN, 'Sec-Fetch-Site': 'same-origin', 'X-CareerLens-Local': '1'}


@pytest.fixture
def browser_client(database, settings):
    with TestClient(create_app(settings), base_url=ORIGIN, client=('127.0.0.1', 32100)) as client:
        yield client


def test_browser_cookie_reload_logout_and_token_compatibility(browser_client, settings):
    client = browser_client
    assert client.get('/api/v1/source-boards').status_code == 401
    response = client.post('/api/v1/browser-session', headers=BROWSER, json={})
    assert response.json() == {'connected': True}
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/api/v1' in cookie
    private = identity(settings).token
    assert private not in response.text and private not in cookie
    assert client.get('/api/v1/source-boards', headers=BROWSER).status_code == 200
    assert client.get('/').status_code == 200  # Page reload does not revoke the session.
    assert client.get('/api/v1/source-boards', headers=BROWSER).status_code == 200
    assert client.get('/api/v1/source-boards', headers={**BROWSER, 'X-CareerLens-Token': 'invalid'}).status_code == 401
    refresh = client.post(f'/api/v1/source-boards/{BOARD_ID}/refresh', json={}, headers={**BROWSER, 'Idempotency-Key': 'browser-test'})
    assert refresh.status_code == 202
    old_cookie = client.cookies.get(COOKIE)
    assert client.post('/api/v1/browser-session/disconnect', headers=BROWSER, json={}).json() == {'connected': False}
    assert not client.cookies.get(COOKIE)
    client.cookies.set(COOKIE, old_cookie)
    assert client.get('/api/v1/source-boards', headers=BROWSER).status_code == 401
    assert client.get('/api/v1/source-boards', headers={'X-CareerLens-Token': private}).status_code == 200


@pytest.mark.parametrize('overrides', [
    {'Origin': 'http://localhost:8000'}, {'Origin': 'http://127.0.0.1:9000'},
    {'Origin': 'null'}, {'Origin': ''}, {'Sec-Fetch-Site': 'same-site'},
    {'Sec-Fetch-Site': 'cross-site'}, {'Sec-Fetch-Site': ''}, {'X-CareerLens-Local': ''},
])
def test_bootstrap_requires_exact_origin_and_browser_metadata(browser_client, overrides):
    response = browser_client.post('/api/v1/browser-session', headers={**BROWSER, **overrides}, json={})
    assert response.status_code == 403
    assert 'set-cookie' not in response.headers


def test_no_cookie_bootstrap_for_remote_peer_or_form(database, settings, browser_client):
    assert browser_client.post('/api/v1/browser-session', headers=BROWSER, content='form=value').status_code == 403
    with TestClient(create_app(settings), base_url=ORIGIN, client=('192.0.2.5', 30000)) as remote:
        assert remote.post('/api/v1/browser-session', headers=BROWSER, json={}).status_code == 403


def test_cookie_cannot_cross_port_or_origin_or_bypass_mutation_guard(browser_client):
    browser_client.post('/api/v1/browser-session', headers=BROWSER, json={})
    assert browser_client.get('/api/v1/source-boards').status_code == 403
    assert browser_client.get('/api/v1/source-boards', headers={**BROWSER, 'Origin': 'http://localhost:8000'}).status_code == 403
    assert browser_client.get('/api/v1/source-boards', headers={**BROWSER, 'Host': '127.0.0.1:9000', 'Origin': 'http://127.0.0.1:9000'}).status_code == 403
    assert browser_client.post(f'/api/v1/source-boards/{BOARD_ID}/refresh', headers={'Sec-Fetch-Site': 'same-origin', 'Idempotency-Key': 'guard'}, json={}).status_code == 403
    browser_client.cookies.set(COOKIE, 'forged')
    assert browser_client.get('/api/v1/source-boards', headers=BROWSER).status_code == 401


def test_session_expiry_and_restart_revoke_capability(browser_client, settings, database, monkeypatch):
    browser_client.post('/api/v1/browser-session', headers=BROWSER, json={})
    cookie = browser_client.cookies.get(COOKIE)
    from app.core import security
    now = security.time.monotonic()
    monkeypatch.setattr(security, 'session_clock', lambda: now + security.SESSION_SECONDS + 1)
    assert browser_client.get('/api/v1/source-boards', headers=BROWSER).status_code == 401
    with TestClient(create_app(settings), base_url=ORIGIN, client=('127.0.0.1', 32100)) as restarted:
        restarted.cookies.set(COOKIE, cookie)
        assert restarted.get('/api/v1/source-boards', headers=BROWSER).status_code == 401


def test_only_frontend_directory_is_served_and_csp_is_restrictive(client, settings):
    response = client.get('/')
    assert response.status_code == 200
    assert "script-src 'self'" in response.headers['content-security-policy']
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']
    assert response.headers['x-frame-options'] == 'DENY'
    assert 'no-store' in response.headers['cache-control']
    assert identity(settings).token not in response.text
    for path in ['/web/.env', '/web/local-session.json', '/web/../app/core/config.py', '/data/backend/local-session.json']:
        assert client.get(path).status_code == 404
    assert client.get('/web/js/main.js').status_code == 200
    assert client.get('/docs').status_code == 200
