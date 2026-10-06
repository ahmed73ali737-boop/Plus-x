import json
from pathlib import Path
from app.server import create_app
ROOT=Path(__file__).resolve().parents[1]

def test_api_contract_snapshot_and_operation_ids():
    schema=create_app('sqlite:///:memory:',origin='http://testserver',seed_demo=False).openapi()
    methods={'get','post','put','patch','delete'}
    current={path:sorted(m for m in item if m in methods) for path,item in sorted(schema['paths'].items())}
    expected=json.loads((ROOT/'ops/api-contract-v1.json').read_text(encoding='utf-8'))
    assert current==expected
    ops=[item[m]['operationId'] for item in schema['paths'].values() for m in item if m in methods]
    assert len(ops)==len(set(ops)) and len(ops)>=40

def test_critical_api_surface_present():
    contract=json.loads((ROOT/'ops/api-contract-v1.json').read_text(encoding='utf-8'))
    for path in [
        '/api/auth/login','/api/public/site/{slug}','/api/collect','/api/admin/sites',
        '/api/admin/sites/{sid}/publish','/api/admin/sites/{sid}/imports/preview',
        '/api/admin/sites/{sid}/metrics','/api/admin/sites/{sid}/devices',
        '/api/device/heartbeat','/api/admin/organizations','/api/admin/audit',
        '/api/public/events/{event_slug}/guests/register',
        '/api/public/events/{event_slug}/guests/{guest_number}/qr',
        '/api/device/events/{event_id}/guest-manifest',
        '/api/device/events/{event_id}/guest-checkins']:
        assert path in contract


def test_mjs_assets_use_javascript_mime_type(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'mime.sqlite'),origin='http://testserver',seed_demo=True)
    c=TestClient(app)
    for path in ['/assets/app.mjs','/assets/public.mjs','/assets/ui.mjs','/assets/offline.mjs']:
        response=c.get(path)
        assert response.status_code==200, path
        content_type=response.headers.get('content-type','').lower()
        assert 'javascript' in content_type, (path,content_type)
