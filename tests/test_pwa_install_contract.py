"""Verify install manifest, public PNG icons, HTML and offline shell assets."""
from __future__ import annotations
import struct
import pytest
from fastapi.testclient import TestClient
from app.server import create_app

@pytest.fixture
def client(tmp_path):
    return TestClient(create_app('sqlite:///'+str(tmp_path/'pwa.sqlite'),origin='http://testserver',seed_demo=False))

def test_pwa_icons_manifest_are_real_pngs_with_safe_sizes(client):
    response=client.get('/assets/manifest.webmanifest')
    assert response.status_code==200
    manifest=response.json()
    assert manifest['start_url']=='/' and manifest['scope']=='/' and manifest['id']=='/'
    assert manifest['display']=='standalone'
    icons={entry['sizes']:entry for entry in manifest['icons']}
    assert set(icons)>={'192x192','512x512'}
    for size in (192,512):
        icon=icons[f'{size}x{size}']
        assert icon['type']=='image/png'
        assert 'maskable' in icon['purpose'].split()
        r=client.get(icon['src'])
        assert r.status_code==200
        assert r.headers['content-type'].startswith('image/png')
        assert r.content[:8]==b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II',r.content[16:24])==(size,size)

def test_pwa_assets_are_precached_and_ios_has_touch_icon(client):
    html=client.get('/').text
    assert '<link rel="manifest" href="/assets/manifest.webmanifest">' in html
    assert 'apple-touch-icon' in html
    js=client.get('/sw.js')
    assert js.status_code==200
    assert 'px-shell-v25' in js.text
    for src in ('/assets/icon-192.png','/assets/icon-512.png',
                '/assets/storyboard-core.mjs','/assets/storyboard.mjs',
                '/assets/storyboard.css'):
        assert src in js.text
