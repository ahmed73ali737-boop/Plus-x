"""Destructive native PostgreSQL acceptance for a dedicated TEST database only.
Requires PX_POSTGRES_TEST_URL and PX_ALLOW_POSTGRES_TEST_RESET=YES.
Never point this script at production.
"""
from __future__ import annotations
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json, os, sys, uuid
from sqlalchemy import text
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.db import make_engine, metadata
from tools.migrate_postgres import apply_migrations, execute_script
from app.server import create_app

url=os.environ.get('PX_POSTGRES_TEST_URL','')
allow=os.environ.get('PX_ALLOW_POSTGRES_TEST_RESET','')=='YES'
if not url.startswith('postgresql+psycopg://') or not allow:
    print(json.dumps({'status':'blocked','reason':'Set PX_POSTGRES_TEST_URL to a dedicated PostgreSQL test DB and PX_ALLOW_POSTGRES_TEST_RESET=YES.'},indent=2))
    raise SystemExit(3)

engine=make_engine(url)
if engine.dialect.name!='postgresql': raise SystemExit('POSTGRESQL_REQUIRED')
metadata.drop_all(engine)
with engine.begin() as con:
    con.exec_driver_sql('DROP TABLE IF EXISTS px_schema_migrations')
    execute_script(con,(ROOT/'ops/001_full_schema_postgres.sql').read_text(encoding='utf-8'))
migration_result=apply_migrations(engine)
assert '004_windows12_guest_identity.sql' in migration_result['applied']
migration_repeat=apply_migrations(engine)
assert not migration_repeat['applied'] and len(migration_repeat['skipped'])==4
app=create_app(url,origin='http://testserver',seed_demo=True)
c=TestClient(app)
checks=[]
def ok(name,cond=True):
    assert cond,name; checks.append(name)

ok('postgres_dialect',app.state.engine.dialect.name=='postgresql')
ok('migration_runner_applied_guest_schema','004_windows12_guest_identity.sql' in migration_result['applied'])
ok('migration_runner_idempotent',not migration_repeat['applied'] and len(migration_repeat['skipped'])==4)
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

def concurrent_guest_register(i):
    phone='0777 909 090' if i%2==0 else '+967 777 909 090'
    with TestClient(app) as client:
        response=client.post('/api/public/events/demo/guests/register',json={
            'phone':phone,'country_code':'+967','consent':True,'name':'Concurrent Guest'
        })
        return response.status_code,response.json()

with ThreadPoolExecutor(max_workers=8) as pool:
    concurrent_results=list(pool.map(concurrent_guest_register,range(16)))
ok('concurrent_guest_requests_all_200',all(code==200 for code,_ in concurrent_results))
numbers={body.get('guest_number') for _,body in concurrent_results}
ok('concurrent_same_phone_one_guest_number',len(numbers)==1 and None not in numbers)
with engine.connect() as con:
    ok('concurrent_same_phone_one_guest_row',con.execute(text("select count(*) from px_guests where phone_e164='+967777909090'")).scalar_one()==1)
    ok('concurrent_same_phone_one_event_registration',con.execute(text("select count(*) from px_event_guests eg join px_guests g on g.id=eg.guest_id where eg.event_id='event-demo' and g.phone_e164='+967777909090'")).scalar_one()==1)

gate=c.post('/api/admin/sites/event-demo/devices',json={'name':'Concurrent Gate','device_type':'operator'})
ok('event_gate_device_created',gate.status_code==200)
gate_token=gate.json()['device_token']
gate_guest=c.post('/api/public/events/demo/guests/register',json={'phone':'777919191','country_code':'+967','consent':True}).json()

def concurrent_gate_entry(_):
    with TestClient(app) as client:
        response=client.post('/api/device/events/event-demo/guest-checkins',headers={'X-PulseX-Device-Token':gate_token},json={'items':[{
            'scan_id':str(uuid.uuid4()),'guest_number':gate_guest['guest_number'],'direction':'entry','checkpoint':'concurrent'
        }]})
        return response.status_code,response.json()['receipts'][0]['status']

with ThreadPoolExecutor(max_workers=8) as pool:
    gate_results=list(pool.map(concurrent_gate_entry,range(8)))
ok('concurrent_gate_requests_all_200',all(code==200 for code,_ in gate_results))
statuses=[status for _,status in gate_results]
ok('concurrent_gate_single_entry',statuses.count('accepted')==1 and statuses.count('already_inside')==7)
with engine.connect() as con:
    ok('concurrent_gate_one_checkin_row',con.execute(text("select count(*) from px_guest_checkins where guest_number=:n"),{'n':gate_guest['guest_number']}).scalar_one()==1)
report={'status':'passed','checks':checks,'database':'PostgreSQL','warning':'Application scope isolation was exercised; PostgreSQL RLS policies are not claimed by this script.'}
(ROOT/'qa/postgres-native-acceptance.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
