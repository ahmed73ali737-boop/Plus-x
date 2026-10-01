import json
from pathlib import Path
from app.server import create_app
ROOT=Path(__file__).resolve().parents[1]

def test_api_contract_snapshot_and_operation_ids():
    schema=create_app('sqlite:///:memory:',origin='http://testserver',seed_demo=False).openapi()
    methods={'get','post','put','patch','delete'}
    current={path:sorted(m for m in item if m in methods) for path,item in sorted(schema['paths'].items())}
    expected=json.loads((ROOT/'ops/api-contract-v1.json').read_text())
    assert current==expected
    ops=[item[m]['operationId'] for item in schema['paths'].values() for m in item if m in methods]
    assert len(ops)==len(set(ops)) and len(ops)>=40

def test_critical_api_surface_present():
    contract=json.loads((ROOT/'ops/api-contract-v1.json').read_text())
    for path in [
        '/api/auth/login','/api/public/site/{slug}','/api/collect','/api/admin/sites',
        '/api/admin/sites/{sid}/publish','/api/admin/sites/{sid}/imports/preview',
        '/api/admin/sites/{sid}/metrics','/api/admin/sites/{sid}/devices',
        '/api/device/heartbeat','/api/admin/organizations','/api/admin/audit']:
        assert path in contract
