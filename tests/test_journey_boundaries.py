"""Disposable ASGI and transformed-JS contracts; no browser/provider acceptance."""
import shutil
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.server import create_app
from app.core.settings import load_settings
from test_development_web import adapter

@pytest.mark.parametrize('prefix', ['', '/plusx'])
def test_generated_links_and_qr_keep_mount(tmp_path, monkeypatch, prefix):
    monkeypatch.setenv('PUBLIC_PATH_PREFIX', prefix)
    app = create_app('sqlite:///'+str(tmp_path/'test.sqlite'), origin='http://testserver', seed_demo=True)
    try:
        with TestClient(app) as client:
            cred = next(x for x in app.state.seed_credentials if x['email']=='admin@pulsex.test')
            auth = client.post('/api/auth/login', json={'email':cred['email'],'password':cred['password']})
            assert auth.status_code == 200
            client.headers.update({'Origin':'http://testserver','X-CSRF':auth.json()['csrf']})
            captured = []
            import qrcode
            make = qrcode.make
            monkeypatch.setattr(qrcode, 'make', lambda value: (captured.append(value), make(value))[1])
            assert client.get('/api/admin/sites/event-demo/qr').status_code == 200
            assert captured == ['http://testserver'+prefix+'/e/demo?source=qr']
            invite = client.post('/api/admin/events/event-demo/invitations', json={'name':'Mount test','phone':'777444222'} )
            assert invite.status_code == 200, invite.text
            assert invite.json()['invitation_url'].startswith('http://testserver'+prefix+'/invite/')
            guest = client.post('/api/public/events/demo/guests/register', json={'name':'Mount Guest','phone':'777123456','country_code':'+967','consent':True})
            assert guest.status_code == 200, guest.text
            assert guest.json()['qr_url'].startswith('http://testserver'+prefix+'/e/demo/guest/')
            # Prefix configuration must not change CSRF's origin boundary.
            denied = client.post('/api/auth/logout', headers={'Origin':'http://evil.example'})
            assert denied.status_code == 403
    finally:
        app.state.engine.dispose()

@pytest.mark.parametrize('prefix', ['/', '//evil', '/plusx/', '/a/../b', '/a?b', '/a#b', '/a%2fb', 'plusx'])
def test_invalid_mount_rejected(monkeypatch, prefix):
    monkeypatch.setenv('PUBLIC_PATH_PREFIX', prefix)
    with pytest.raises(ValueError, match='INVALID_PUBLIC_PATH_PREFIX'):
        load_settings()

def test_transformed_runtime_boundaries(tmp_path):
    shutil.copytree('web', tmp_path/'web')
    adapter.prepare(tmp_path/'web')
    result = subprocess.run(['node','--experimental-vm-modules','--test','tests/journey_boundaries.mjs'], env={**__import__('os').environ,'JOURNEY_WEB':str(tmp_path/'web')}, capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stdout+result.stderr

def test_android_remains_withdrawn():
    from fastapi import FastAPI
    from app.api.routers.downloads import create_download_router
    app = FastAPI()
    app.include_router(create_download_router(Path('.')))
    with TestClient(app) as client:
        info = client.get('/api/downloads/android').json()
        assert info['available'] is False and info['channel'] == 'withdrawn'
        for name in ('eventna', 'pulsex'):
            for method in ('GET', 'HEAD'):
                response = client.request(method, f'/downloads/{name}-android-preview.apk')
                assert response.status_code == 410
                assert response.headers['cache-control'] == 'no-store'
