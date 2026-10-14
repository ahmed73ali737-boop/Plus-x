"""Live Wall v1 is read-only and honors published moderator visibility."""
from __future__ import annotations

from fastapi.testclient import TestClient
from app.server import create_app


def make_client(tmp_path):
    app = create_app('sqlite:///' + str(tmp_path / 'livewall.sqlite3'),
                     origin='http://testserver', seed_demo=True)
    return app, TestClient(app)


def test_live_wall_route_and_assets(tmp_path):
    _, client = make_client(tmp_path)
    response = client.get('/live/agency-01')
    assert response.status_code == 200
    assert '/assets/app.mjs' in response.text
    assert client.get('/assets/livewall.mjs').status_code == 200
    assert client.get('/assets/livewall.css').status_code == 200


def test_live_wall_results_can_be_withdrawn_by_publishing(tmp_path):
    app, client = make_client(tmp_path)
    creds = app.state.seed_credentials[2]
    response = client.post('/api/auth/login', json={
        'email': creds['email'], 'password': creds['password']})
    assert response.status_code == 200
    client.headers['X-CSRF'] = response.json()['csrf']
    path = '/api/admin/sites/agency-01'
    response = client.get(path)
    assert response.status_code == 200
    site = response.json()
    poll = next(r for r in site['draft']['records'] if r['kind'] == 'poll')
    code = poll['code']

    # Draft update must be explicitly published by the authorized admin.
    poll['show_results'] = False
    saved = client.put(path, json={'draft_rev': site['draft_rev'],
                                   'config': site['draft']})
    assert saved.status_code == 200, saved.text
    published = client.post(path + '/publish', json={
        'draft_rev': saved.json()['draft_rev']})
    assert published.status_code == 200, published.text
    public = client.get('/api/public/site/agency-01/results')
    assert public.status_code == 200
    assert code not in public.json()['polls']

    # Never expose raw visitor submissions or PII to a public screen.
    for private_field in ('visitor_id', 'guest_number', 'phone', 'email',
                          'follow_requests'):
        assert private_field not in public.text
