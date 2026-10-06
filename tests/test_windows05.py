from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / 'sdk/python') not in sys.path:
    sys.path.insert(0, str(ROOT / 'sdk/python'))

from app.application.access import active_window
from app.core.security import hash_password, verify_password
from app.server import create_app
from app.core.build_info import BUILD_LABEL
from pulsex_sdk import PulseXClient


def test_password_service_roundtrip_and_rejects_short():
    encoded = hash_password('correct-horse-battery-staple')
    assert verify_password('correct-horse-battery-staple', encoded)
    assert not verify_password('wrong-password-value', encoded)
    with pytest.raises(Exception):
        hash_password('short')


def test_access_window_rules():
    assert active_window({'status': 'active', 'valid_from': None, 'valid_until': None})
    assert not active_window({'status': 'suspended', 'valid_from': None, 'valid_until': None})
    assert not active_window({'status': 'active', 'valid_until': '2000-01-01T00:00:00+00:00'})


def test_health_readiness_and_api_version(tmp_path):
    app = create_app(f"sqlite:///{tmp_path/'w05.sqlite3'}", origin='http://testserver', seed_demo=True, credentials_path=tmp_path/'creds.json')
    client = TestClient(app)
    h = client.get('/api/health')
    assert h.status_code == 200 and h.json()['build'] == BUILD_LABEL
    assert h.headers['X-PulseX-API-Version'] == '1'
    assert client.get('/api/health/live').json()['status'] == 'ok'
    assert client.get('/api/health/ready').json()['status'] == 'ready'


def test_security_headers_hsts_only_under_https(tmp_path):
    app = create_app(f"sqlite:///{tmp_path/'secure.sqlite3'}", origin='https://testserver', seed_demo=False)
    client = TestClient(app, base_url='https://testserver')
    r = client.get('/api/health')
    assert r.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'Strict-Transport-Security' in r.headers
    assert r.headers['Cache-Control'] == 'no-store'


def test_python_sdk_against_real_local_http_shape(tmp_path, monkeypatch):
    # This test validates the SDK URL/JSON/cookie/CSRF behavior using a tiny fake opener.
    class Resp:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self): return json.dumps(self.body).encode()
    calls = []
    class Opener:
        def open(self, req, timeout=None):
            calls.append((req.method, req.full_url, dict(req.headers), req.data))
            if req.full_url.endswith('/api/auth/login'):
                return Resp({'user': {'id':'u1'}, 'csrf':'csrf-1'})
            if req.full_url.endswith('/api/admin/sites'):
                return Resp({'sites': []})
            return Resp({'status':'ok'})
    sdk = PulseXClient('http://localhost:4310')
    sdk.opener = Opener()
    assert sdk.login('a@example.test','long-enough-password')['id'] == 'u1'
    assert sdk.admin_sites() == {'sites': []}
    assert sdk.csrf == 'csrf-1'
    assert calls[0][0] == 'POST'


def test_openapi_contains_hardening_health_paths(tmp_path):
    app = create_app(f"sqlite:///{tmp_path/'schema.sqlite3'}", seed_demo=False)
    schema = app.openapi()
    assert schema['info']['version'] == '0.9.0'
    assert '/api/health/ready' in schema['paths']
    assert '/api/admin/organizations' in schema['paths']

def test_valid_media_upload_uses_content_hash(tmp_path):
    import base64
    app = create_app(f"sqlite:///{tmp_path/'media.sqlite3'}", origin='http://testserver', seed_demo=True, credentials_path=tmp_path/'creds.json')
    client = TestClient(app)
    creds = app.state.seed_credentials[2]
    auth = client.post('/api/auth/login', json={'email':creds['email'],'password':creds['password']}).json()
    client.headers['X-CSRF'] = auth['csrf']
    # Minimal PNG signature + bounded bytes is accepted by the pilot media gate.
    raw = b'\x89PNG\r\n\x1a\n' + b'X' * 32
    response = client.post('/api/admin/media', json={'base64': base64.b64encode(raw).decode()})
    assert response.status_code == 200
    assert response.json()['url'].endswith('.png')
