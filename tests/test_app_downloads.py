import hashlib,json
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func,select
from app.server import create_app
from app.db import users,signup_requests
from app.api.routers.downloads import create_download_router,APK_NAME
from harness_support import app_client

ROOT=Path(__file__).resolve().parents[1]


def test_anonymous_download_matches_pinned_apk_and_headers(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'download.sqlite'),origin='http://testserver',seed_demo=False)
    with app_client(app) as client:
        meta=client.get('/api/downloads/android')
        assert meta.status_code==200
        data=meta.json()
        assert data['channel']=='preview' and not data['production_signed'] and not data['device_tested']
        response=client.get(data['download_url'])
        assert response.status_code==200
        assert response.headers['content-type']=='application/vnd.android.package-archive'
        assert response.headers['x-content-type-options']=='nosniff'
        assert 'attachment' in response.headers['content-disposition']
        assert len(response.content)==data['bytes']==299736
        assert hashlib.sha256(response.content).hexdigest()==data['sha256']
        assert client.head(data['download_url']).content==b''
        assert client.get('/api/admin/sites').status_code==401


@pytest.mark.parametrize('failure',['missing','tampered','wrong-size','untrusted-signing'])
def test_download_fails_closed_instead_of_serving_wrong_binary(tmp_path,failure):
    folder=tmp_path/'artifacts/android';folder.mkdir(parents=True)
    evidence=json.loads((ROOT/'artifacts/android/BUILD_EVIDENCE.json').read_text())
    if failure!='missing':(folder/APK_NAME).write_bytes((ROOT/'artifacts/android'/APK_NAME).read_bytes())
    if failure=='tampered':(folder/APK_NAME).write_bytes(b'not the tested APK')
    if failure=='wrong-size':evidence['apk_bytes']+=1
    if failure=='untrusted-signing':evidence['signing']='production'
    (folder/'BUILD_EVIDENCE.json').write_text(json.dumps(evidence))
    app=FastAPI();app.include_router(create_download_router(tmp_path))
    with TestClient(app) as client:
        for endpoint in ['/api/downloads/android','/downloads/pulsex-android-preview.apk']:
            response=client.get(endpoint)
            assert response.status_code==503
            assert response.json()['detail']=='ANDROID_PREVIEW_UNAVAILABLE'
        assert client.get('/downloads/BUILD_EVIDENCE.json').status_code==404


def test_account_request_creates_pending_only_and_no_user_or_permissions(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'signup.sqlite'),origin='http://testserver',seed_demo=True)
    with app_client(app) as client:
        with app.state.engine.connect() as c:before=c.execute(select(func.count()).select_from(users)).scalar_one()
        payload={'site_id':'platform','requested_role':'organizer','organization_name':'Synthetic org',
                 'contact_name':'Synthetic contact','email':'onboarding@example.test','phone':'',
                 'wants_account':True,'participation_type':'exhibitor'}
        result=client.post('/api/signup-request',json=payload)
        assert result.status_code==200
        assert result.json()['status']=='pending' and result.json()['grants_access'] is False
        with app.state.engine.connect() as c:
            assert c.execute(select(func.count()).select_from(users)).scalar_one()==before
            assert c.execute(select(signup_requests.c.status)).scalar_one()=='pending'
        assert client.post('/api/auth/login',json={'email':payload['email'],'password':'UnassignedPassword42!'}).status_code==401


def test_access_page_and_lazy_assets_are_public_and_precached(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'page.sqlite'),seed_demo=False)
    with app_client(app) as client:
        assert client.get('/start').status_code==200
        for name in ['access.mjs','access.css']:
            response=client.get('/assets/'+name)
            assert response.status_code==200
            assert '/assets/'+name in client.get('/sw.js').text
        assert "import('./access.mjs')" in client.get('/assets/app.mjs').text

def test_public_account_requests_have_separate_bounded_rate_limit(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'rate.sqlite'),origin='http://testserver',seed_demo=True)
    with app_client(app) as client:
        payload={'site_id':'platform','requested_role':'organizer','organization_name':'Synthetic','contact_name':'QA','email':'qa@example.test'}
        for _ in range(10):assert client.post('/api/signup-request',json=payload).status_code==200
        response=client.post('/api/signup-request',json=payload)
        assert response.status_code==429
        assert response.headers['Retry-After']=='60'
        assert client.get('/api/downloads/android').status_code==200
