"""B-02 rollback boundary and secret-free denial persistence contracts."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select
from app.server import create_app
from app.db import audit, sites
from app.domain import default_config
from app.application.audit_service import AuditedDenial, DenialAuditWriter


@pytest.fixture
def system(tmp_path):
    app = create_app('sqlite:///'+str(tmp_path/'audit.sqlite'), seed_demo=True)
    with TestClient(app) as client:
        yield app, client


def rows(app):
    with app.state.engine.connect() as conn:
        return conn.execute(select(audit).where(audit.c.action.in_(['login_failed','scope_denied']))).mappings().all()


def test_rollback_then_independent_audit_commit(system):
    app, client = system
    # Insert before the SPA catch-all.
    @app.get('/api/test-denial')
    def denied():
        with app.state.engine.begin() as conn:
            conn.execute(insert(sites).values(id='rolled-back',slug='rolled-back',kind='event',draft=default_config('Rollback','event'),draft_rev=1,published_version=0))
            raise AuditedDenial('FORBIDDEN_SCOPE',403,action='scope_denied',user={'id':'trusted-actor'},site_id='event-demo')
    route = app.router.routes.pop()
    app.router.routes.insert(0, route)
    assert client.get('/api/test-denial').status_code == 403
    with app.state.engine.connect() as conn:
        assert conn.execute(select(sites).where(sites.c.id=='rolled-back')).first() is None
    assert len(rows(app)) == 1
    assert rows(app)[0]['user_id'] == 'trusted-actor'


def test_storage_failure_does_not_change_denial_or_leak(system, monkeypatch, caplog):
    app, client = system
    def broken(*args, **kwargs):
        raise RuntimeError('sensitive-driver-parameters')
    monkeypatch.setattr('app.application.audit_service.write_audit', broken)
    for _ in range(2):
        response = client.post('/api/auth/login',json={'email':'raw@example.invalid','password':'secret-password'})
        assert response.status_code == 401 and response.json() == {'detail':'INVALID_CREDENTIALS'}
    assert app.state.denial_audit.failures == 2
    assert app.state.denial_audit.suppressed == 0
    assert not rows(app)
    assert 'sensitive-driver-parameters' not in caplog.text


def test_repeated_login_remains_separate_without_trusting_client_ids(system):
    app, client = system
    for i in range(3):
        assert client.post('/api/auth/login',headers={'X-Request-ID':str(i)},json={'email':f'raw{i}@example.invalid','password':'secret-password'}).status_code == 401
    assert len(rows(app)) == 3
    assert rows(app)[0]['user_id'] is None and rows(app)[0]['site_id'] is None
    assert rows(app)[0]['details'] == {'reason':'INVALID_CREDENTIALS'}
    assert app.state.denial_audit.suppressed == 0
    assert client.get('/api/admin/audit').status_code == 401


def test_deduplication_expires_and_global_budget_is_bounded(system):
    app, _ = system
    clock = [0]
    writer = DenialAuditWriter(app.state.engine,clock=lambda:clock[0])
    for i in range(650):
        writer.record(AuditedDenial('FORBIDDEN_SCOPE',403,action='scope_denied',user={'id':str(i)},site_id='event-demo'))
    assert len(rows(app)) == 600 and len(writer.recent) == 600
    assert writer.suppressed == 50
    clock[0] = 61
    writer.record(AuditedDenial('FORBIDDEN_SCOPE',403,action='scope_denied',user={'id':'0'},site_id='event-demo'))
    assert len(rows(app)) == 601


def test_same_denial_is_written_once(system):
    app, _ = system
    denial = AuditedDenial('FORBIDDEN_SCOPE',403,action='scope_denied')
    app.state.denial_audit.record(denial)
    app.state.denial_audit.record(denial)
    assert len(rows(app)) == 1
    assert app.state.denial_audit.suppressed == 1


def test_failure_records_are_platform_only_when_unscoped(system):
    app, client = system
    assert client.post('/api/auth/login',json={'email':'raw@example.invalid','password':'secret-password'}).status_code == 401
    for role in ('platform','organizer','agency'):
        credential = next(x for x in app.state.seed_credentials if x['role']==role)
        with TestClient(app) as reader:
            assert reader.post('/api/auth/login',json={'email':credential['email'],'password':credential['password']}).status_code == 200
            response = reader.get('/api/admin/audit')
            assert response.status_code == 200
            found = [r for r in response.json()['entries'] if r['action']=='login_failed']
            assert bool(found) == (role=='platform')
