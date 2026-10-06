import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.server import create_app
from app.core.build_info import BUILD_LABEL

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture(scope='module')
def app(tmp_path_factory):
    root=tmp_path_factory.mktemp('w07')
    return create_app('sqlite:///'+str(root/'test.sqlite'),origin='http://testserver',seed_demo=True)

@pytest.fixture
def client(app):
    return TestClient(app,client=('w07-'+uuid.uuid4().hex,51000))

def login(c,app,index=0):
    u=app.state.seed_credentials[index]
    r=c.post('/api/auth/login',json={'email':u['email'],'password':u['password']})
    assert r.status_code==200,r.text
    c.headers['X-CSRF']=r.json()['csrf']
    return r.json()['user']


def test_windows07_version_and_device_schema(client):
    h=client.get('/api/health').json()
    assert h['build']==BUILD_LABEL
    assert client.app.openapi()['info']['version']=='0.9.0'
    paths=client.app.openapi()['paths']
    assert '/api/admin/sites/{sid}/devices' in paths
    assert '/api/device/heartbeat' in paths


def test_admin_device_lifecycle(client,app):
    login(client,app,1)  # organizer
    created=client.post('/api/admin/sites/agency-01/devices',json={'name':'Kiosk A','device_type':'kiosk','app_version':'0.9.0'})
    assert created.status_code==200,created.text
    payload=created.json(); token=payload['device_token']; did=payload['id']
    listed=client.get('/api/admin/sites/agency-01/devices').json()['devices']
    device=next(x for x in listed if x['id']==did)
    assert device['name']=='Kiosk A' and device['device_type']=='kiosk'
    assert 'device_token' not in device and 'token_hash' not in device

    hb=client.post('/api/device/heartbeat',headers={'X-PulseX-Device-Token':token},json={'pending_count':7,'app_version':'0.7.1','synced':True,'metadata':{'browser':'edge'}})
    assert hb.status_code==200,hb.text
    assert hb.json()['pending_count']==7 and hb.json()['last_sync_at']

    stopped=client.patch(f'/api/admin/sites/agency-01/devices/{did}',json={'status':'disabled'})
    assert stopped.status_code==200
    assert client.post('/api/device/heartbeat',headers={'X-PulseX-Device-Token':token},json={'pending_count':0}).status_code==401


def test_device_scope_isolation(client,app):
    login(client,app,2)  # agency-01
    assert client.get('/api/admin/sites/agency-02/devices').status_code==403
    assert client.post('/api/admin/sites/agency-01/devices',json={'name':'Operator','device_type':'operator'}).status_code==403
    assert client.post('/api/admin/sites/agency-01/devices',json={'name':'Tablet','device_type':'tablet'}).status_code==200


def test_access_request_review(client,app):
    r=client.post('/api/access-request',json={'site_id':'agency-01','email':'review-me@sample.test','name':'Review Me'})
    assert r.status_code==200
    login(client,app,1)
    reqs=client.get('/api/admin/sites/agency-01/users').json()['requests']
    item=next(x for x in reqs if x['email']=='review-me@sample.test')
    reviewed=client.patch(f"/api/admin/sites/agency-01/access-requests/{item['id']}",json={'status':'rejected'})
    assert reviewed.status_code==200 and reviewed.json()['status']=='rejected'
    after=client.get('/api/admin/sites/agency-01/users').json()['requests']
    assert next(x for x in after if x['id']==item['id'])['status']=='rejected'


def test_user_disable_revokes_login(client,app):
    login(client,app,1)
    made=client.post('/api/admin/sites/agency-08/users',json={'email':'disable-me@sample.test','name':'Disable Me'})
    assert made.status_code==200,made.text
    pw=made.json()['temporary_password']
    users=client.get('/api/admin/sites/agency-08/users').json()['users']
    uid=next(x for x in users if x['email']=='disable-me@sample.test')['id']
    assert client.patch(f'/api/admin/sites/agency-08/users/{uid}',json={'active':False}).json()['sessions_revoked'] is True
    other=TestClient(app)
    assert other.post('/api/auth/login',json={'email':'disable-me@sample.test','password':pw}).status_code==401
    assert client.patch(f'/api/admin/sites/agency-08/users/{uid}',json={'active':True}).status_code==200
    assert other.post('/api/auth/login',json={'email':'disable-me@sample.test','password':pw}).status_code==200


def test_admin_ui_has_devices_and_request_review():
    text=(ROOT/'web/admin.mjs').read_text(encoding='utf-8')
    assert 'الأجهزة والطرفيات' in text
    assert 'رفض الطلب' in text
    assert 'تم إيقاف الحساب وإنهاء جلساته' in text


def test_service_worker_cache_bumped_and_assets_exist():
    sw=(ROOT/'web/sw.js').read_text(encoding='utf-8')
    assert "px-shell-v14" in sw
    import re
    assets=re.findall(r"'/assets/([^']+)'",sw)
    assert assets and all((ROOT/'web'/name).is_file() for name in assets)

def test_offline_device_pairing_hooks_present():
    offline=(ROOT/'web/offline.mjs').read_text(encoding='utf-8')
    public=(ROOT/'web/public.mjs').read_text(encoding='utf-8')
    assert 'saveDeviceToken' in offline and 'deviceHeartbeat' in offline
    assert 'رمز ربط الطرفية' in public and 'X-PulseX-Device-Token' in offline
