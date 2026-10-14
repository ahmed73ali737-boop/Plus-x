"""Draft storyboard reorder persists through existing scoped PulseX API, never publishes implicitly."""
from __future__ import annotations

import copy
from fastapi.testclient import TestClient
from app.server import create_app


def test_storyboard_draft_revision_publish_and_scope(tmp_path):
    app = create_app('sqlite:///' + str(tmp_path / 'storyboard.sqlite3'), origin='http://testserver', seed_demo=True)
    with TestClient(app) as client:
        agency = app.state.seed_credentials[2]
        signed_in = client.post('/api/auth/login', json={'email':agency['email'], 'password':agency['password']})
        assert signed_in.status_code == 200
        client.headers['X-CSRF'] = signed_in.json()['csrf']
        sid = 'agency-01'
        original = client.get('/api/public/site/' + sid).json()['config']['records']
        response = client.get('/api/admin/sites/' + sid)
        assert response.status_code == 200
        current = response.json()
        revised = copy.deepcopy(current['draft'])
        record_order = sorted(revised['records'], key=lambda item:item['order'])
        assert len(record_order) >= 3
        # Move a non-question across other non-question records; preserve relative question order.
        ordinary = [entry for entry in record_order if entry['kind'] not in ('question', 'poll')]
        assert len(ordinary) >= 2
        first, second = ordinary[:2]
        first['order'], second['order'] = second['order'], first['order']
        saved = client.put('/api/admin/sites/' + sid, json={'draft_rev':current['draft_rev'], 'config':revised})
        assert saved.status_code == 200, saved.text
        persisted = client.get('/api/admin/sites/' + sid).json()
        got = {entry['code']: entry['order'] for entry in persisted['draft']['records']}
        assert got[first['code']] == first['order']
        assert got[second['code']] == second['order']
        assert set(got) == {entry['code'] for entry in current['draft']['records']}
        # Another browser or older draft cannot overwrite the new revision.
        duplicate = client.put('/api/admin/sites/' + sid, json={'draft_rev': current['draft_rev'], 'config': revised})
        assert duplicate.status_code == 409
        assert client.get('/api/public/site/' + sid).json()['config']['records'] == original
        published = client.post('/api/admin/sites/' + sid + '/publish',json={'draft_rev': saved.json()['draft_rev']})
        assert published.status_code == 200
        latest = client.get('/api/public/site/' + sid).json()['config']['records']
        assert {r['code']:r['order'] for r in latest} == got
        assert client.get('/api/admin/sites/agency-02').status_code == 403
        assert client.put('/api/admin/sites/agency-02', json={
            'draft_rev':1, 'config': revised
        }).status_code == 403
