from pathlib import Path
import os, subprocess, sys, json
from app.db import metadata
from app.server import create_app
from tests.load_profiles import PROFILES

ROOT=Path(__file__).resolve().parents[1]

def test_v06_openapi_and_build(tmp_path):
    app=create_app(f"sqlite:///{tmp_path/'db.sqlite3'}",seed_demo=False)
    assert app.openapi()['info']['version']=='0.9.0'
    from fastapi.testclient import TestClient
    assert TestClient(app).get('/api/health').json()['build']=='windows-08'

def test_scaled_profiles_are_multiples():
    assert PROFILES['x10']['writes'] >= PROFILES['pilot']['writes']*10
    assert PROFILES['stretch']['writes'] >= PROFILES['pilot']['writes']*25

def test_scale_support_indexes_registered():
    names={i.name for t in metadata.tables.values() for i in t.indexes}
    expected={'px_memberships_org_status','px_memberships_user_status','px_participations_event_status','px_participations_org_status','px_assignments_site_status','px_assignments_user_status','px_audit_site_time','px_audit_user_time'}
    assert expected <= names

def test_production_gate_rejects_insecure_config():
    env={**os.environ,'DATABASE_URL':'sqlite:///x.db','PUBLIC_ORIGIN':'http://localhost:4310','SEED_DEMO':'true','WEB_WORKERS':'1'}
    r=subprocess.run([sys.executable,str(ROOT/'tools/production_gate.py')],env=env,capture_output=True,text=True)
    assert r.returncode==2
    assert json.loads(r.stdout)['status']=='fail'

def test_production_gate_accepts_required_shape():
    env={**os.environ,'DATABASE_URL':'postgresql+psycopg://pulsex:0123456789abcdef@postgres:5432/pulsex','PUBLIC_ORIGIN':'https://pulsex.example.org','SEED_DEMO':'false','WEB_WORKERS':'4','PX_NATIVE_POSTGRES_ACCEPTED':'true','PX_LOAD_ACCEPTED':'true','PX_SECURITY_ACCEPTED':'true','PX_FIELD_OFFLINE_ACCEPTED':'true'}
    r=subprocess.run([sys.executable,str(ROOT/'tools/production_gate.py')],env=env,capture_output=True,text=True)
    assert r.returncode==0
    assert json.loads(r.stdout)['status']=='pass'

def test_compose_disables_demo_and_configures_workers():
    s=(ROOT/'compose.yaml').read_text(encoding='utf-8')
    assert 'SEED_DEMO: "false"' in s
    assert 'WEB_WORKERS: ${WEB_WORKERS:-4}' in s
