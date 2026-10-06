import json

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import make_engine, sites, users
from app.server import create_app
from tools.bootstrap_production import bootstrap


def test_production_bootstrap_creates_one_platform_admin_then_is_idempotent(tmp_path):
    db_url='sqlite:///'+str(tmp_path/'bootstrap.sqlite')
    engine=make_engine(db_url)
    credentials=tmp_path/'bootstrap-admin.json'

    first=bootstrap(
        engine,
        email='owner@events.test',
        name='First Platform Admin',
        credentials_path=credentials,
    )
    assert first['status']=='bootstrapped'
    assert credentials.is_file()
    payload=json.loads(credentials.read_text(encoding='utf-8'))
    assert payload['email']=='owner@events.test'
    assert payload['must_change_password'] is True
    assert len(payload['temporary_password'])>=12

    with engine.connect() as db:
        assert db.execute(select(func.count()).select_from(sites)).scalar_one()==1
        assert db.execute(select(func.count()).select_from(users)).scalar_one()==1

    second=bootstrap(
        engine,
        email='owner@events.test',
        name='First Platform Admin',
        credentials_path=credentials,
    )
    assert second['status']=='already_initialized'
    with engine.connect() as db:
        assert db.execute(select(func.count()).select_from(users)).scalar_one()==1

    app=create_app(db_url,origin='http://testserver',seed_demo=False)
    client=TestClient(app)
    login=client.post('/api/auth/login',json={'email':payload['email'],'password':payload['temporary_password']})
    assert login.status_code==200
    assert login.json()['user']['role']=='platform'
    assert login.json()['user']['must_change_password'] is True
    client.headers.update({'X-CSRF':login.json()['csrf'],'Origin':'http://testserver'})
    assert client.get('/api/admin/sites').status_code==428

    changed=client.post('/api/auth/password',json={'current':payload['temporary_password'],'password':'A-New-Strong-Password-2026!'})
    assert changed.status_code==200
    relogin=client.post('/api/auth/login',json={'email':payload['email'],'password':'A-New-Strong-Password-2026!'})
    assert relogin.status_code==200
    assert relogin.json()['user']['must_change_password'] is False


def test_production_bootstrap_rejects_invalid_email(tmp_path):
    engine=make_engine('sqlite:///'+str(tmp_path/'invalid.sqlite'))
    try:
        bootstrap(engine,email='not-an-email',name='Admin',credentials_path=tmp_path/'x.json')
    except RuntimeError as exc:
        assert str(exc)=='BOOTSTRAP_ADMIN_EMAIL_INVALID'
    else:
        raise AssertionError('invalid bootstrap email was accepted')
