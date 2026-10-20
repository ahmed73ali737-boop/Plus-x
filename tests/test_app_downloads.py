import hashlib,json,io,subprocess,zipfile
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func,select
from app.server import create_app
from app.db import users,signup_requests
from app.api.routers.downloads import create_download_router,APK_NAME,verify_preview_artifact
from harness_support import app_client

ROOT=Path(__file__).resolve().parents[1]


def test_reported_apk_is_withdrawn_for_anonymous_and_direct_requests(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'download.sqlite'),origin='http://testserver',seed_demo=False)
    with app_client(app) as client:
        data=client.get('/api/downloads/android').json()
        assert data['available'] is False and data['security_status']=='review_required'
        assert 'download_url' not in data and data['web_url']=='/'
        for path in ['/downloads/eventna-android-preview.apk','/downloads/pulsex-android-preview.apk']:
            for method in ('GET','HEAD'):
                response=client.request(method,path)
                assert response.status_code==410
                assert response.headers['cache-control']=='no-store'
                assert response.headers['x-content-type-options']=='nosniff'
        assert client.get('/api/admin/sites').status_code==401


@pytest.mark.parametrize('failure',['missing','tampered','wrong-size','untrusted-signing'])
def test_download_fails_closed_instead_of_serving_wrong_binary(tmp_path,failure):
    folder=tmp_path/'artifacts/android';folder.mkdir(parents=True)
    evidence=json.loads((ROOT/'artifacts/android/BUILD_EVIDENCE.json').read_text())
    synthetic=b'synthetic forensic integrity fixture'
    evidence.update(apk_sha256=hashlib.sha256(synthetic).hexdigest(),apk_bytes=len(synthetic))
    if failure!='missing':(folder/APK_NAME).write_bytes(synthetic)
    if failure=='tampered':(folder/APK_NAME).write_bytes(b'not the tested APK')
    if failure=='wrong-size':evidence['apk_bytes']+=1
    if failure=='untrusted-signing':evidence['signing']='production'
    (folder/'BUILD_EVIDENCE.json').write_text(json.dumps(evidence))
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:
        verify_preview_artifact(tmp_path)
    assert error.value.status_code==503
    assert error.value.detail=='ANDROID_PREVIEW_UNAVAILABLE'


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


def test_distributable_git_archive_omits_reported_apk():
    archive=subprocess.check_output(['git','archive','--worktree-attributes','--format=zip','HEAD'],cwd=ROOT)
    with zipfile.ZipFile(io.BytesIO(archive)) as packed:
        assert not any(name.startswith('artifacts/android/') and name.endswith('.apk') for name in packed.namelist())
        assert 'artifacts/android/BUILD_EVIDENCE.json' in packed.namelist()
