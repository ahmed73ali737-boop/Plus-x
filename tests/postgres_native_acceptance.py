"""Destructive native PostgreSQL acceptance for a dedicated TEST database only.
Requires PX_POSTGRES_TEST_URL and PX_ALLOW_POSTGRES_TEST_RESET=YES.
Never point this script at production.
"""
from __future__ import annotations
from pathlib import Path
import json, os, sys, uuid
from sqlalchemy import text
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.db import make_engine, metadata
from app.server import create_app

url=os.environ.get('PX_POSTGRES_TEST_URL','')
allow=os.environ.get('PX_ALLOW_POSTGRES_TEST_RESET','')=='YES'
if not url.startswith('postgresql+psycopg://') or not allow:
    print(json.dumps({'status':'blocked','reason':'Set PX_POSTGRES_TEST_URL to a dedicated PostgreSQL test DB and PX_ALLOW_POSTGRES_TEST_RESET=YES.'},indent=2))
    raise SystemExit(3)

engine=make_engine(url)
if engine.dialect.name!='postgresql': raise SystemExit('POSTGRESQL_REQUIRED')
metadata.drop_all(engine); metadata.create_all(engine)
app=create_app(url,origin='http://testserver',seed_demo=True)
c=TestClient(app)
checks=[]
def ok(name,cond=True):
    assert cond,name; checks.append(name)

ok('postgres_dialect',app.state.engine.dialect.name=='postgresql')
with engine.connect() as con:
    ok('database_roundtrip',con.execute(text('select 1')).scalar_one()==1)
    tables=set(con.execute(text("select tablename from pg_tables where schemaname='public' and tablename like 'px_%'")).scalars())
    ok('all_metadata_tables_created',set(metadata.tables)<=tables)
accounts=app.state.seed_credentials
r=c.post('/api/auth/login',json={'email':accounts[1]['email'],'password':accounts[1]['password']});ok('organizer_login',r.status_code==200);c.headers['X-CSRF']=r.json()['csrf']
created=c.post('/api/admin/sites/agency-01/devices',json={'name':'Postgres Kiosk','device_type':'kiosk'});ok('device_insert',created.status_code==200)
token=created.json()['device_token']; hb=c.post('/api/device/heartbeat',headers={'X-PulseX-Device-Token':token},json={'pending_count':2,'synced':True});ok('device_heartbeat',hb.status_code==200)
site=c.get('/api/public/site/agency-01').json(); env={'id':str(uuid.uuid4()),'site_id':'agency-01','version':site['version'],'kind':'survey','visitor_id':str(uuid.uuid4()),'session_id':str(uuid.uuid4()),'source':'web','target':'main','payload':{'answers':{'q-interest':'o1','q-rate':5}},'client_time':'2026-09-29T12:00:00+03:00'}
rec=c.post('/api/collect',json={'items':[env]}).json()['receipts'][0];ok('submission_insert',rec['status']=='accepted')
rec2=c.post('/api/collect',json={'items':[env]}).json()['receipts'][0];ok('idempotent_replay',rec2['status']=='duplicate')
with engine.connect() as con:
    ok('foreign_keys_present',con.execute(text("select count(*) from information_schema.table_constraints where constraint_type='FOREIGN KEY' and table_schema='public'")).scalar_one()>0)
report={'status':'passed','checks':checks,'database':'PostgreSQL','warning':'Application scope isolation was exercised; PostgreSQL RLS policies are not claimed by this script.'}
(ROOT/'qa/postgres-native-acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
