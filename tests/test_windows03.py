"""Regression additions for the Windows-focused UI release; run on the reported OS only."""
import json
import sqlite3
import sys
import zipfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.server import create_app
from app.core.build_info import BUILD_LABEL
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import launcher, backup_local

@pytest.fixture
def isolated(tmp_path):
    app=create_app('sqlite:///'+str(tmp_path/'db.sqlite'),origin='http://testserver',seed_demo=True,credentials_path=tmp_path/'حسابات.json')
    c=TestClient(app)
    u=app.state.seed_credentials[0]
    auth=c.post('/api/auth/login',json={'email':u['email'],'password':u['password']}).json()
    c.headers['X-CSRF']=auth['csrf']
    return c,app,tmp_path

def test_unicode_accounts_are_utf8(isolated):
    c,a,p=isolated
    assert len(json.loads((p/'حسابات.json').read_text(encoding='utf-8')))==12

def test_build_identification(isolated):
    c,_,_=isolated
    assert c.get('/api/health').json()['build']==BUILD_LABEL

def test_non_demo_event_slug_available_to_agency(isolated):
    c,a,_=isolated
    event=c.post('/api/admin/sites',json={'kind':'event','parent_id':'platform','slug':'custom-expo','title':'فعالية أخرى'}).json()
    agency=c.post('/api/admin/sites',json={'kind':'agency','parent_id':event['id'],'slug':'custom-brand','title':'جهة أخرى'}).json()
    assert c.get('/api/admin/sites/'+agency['id']).json()['event_slug']=='custom-expo'

def test_immutable_poll_results_do_not_mix_versions(isolated):
    import uuid
    c,_,_=isolated
    item={'id':str(uuid.uuid4()),'site_id':'agency-01','version':1,'kind':'poll','visitor_id':str(uuid.uuid4()),'session_id':str(uuid.uuid4()),'source':'web','target':'p-first','payload':{'answer':'o1'},'client_time':'2026-09-28T00:00:00Z'}
    assert c.post('/api/collect',json={'items':[item]}).json()['receipts'][0]['status']=='accepted'
    assert c.get('/api/public/site/agency-01/results').json()['polls']['p-first']['ballots']==1
    d=c.get('/api/admin/sites/agency-01').json()
    c.post('/api/admin/sites/agency-01/publish',json={'draft_rev':d['draft_rev']})
    result=c.get('/api/public/site/agency-01/results').json()
    assert result['version']==2 and result['polls']['p-first']['ballots']==0
    metric=c.get('/api/admin/sites/agency-01/metrics').json()
    assert metric['question_labels']['agency-01 / v1 / p-first']['title']=='ما الأولوية التي تهمك؟'

def test_new_assets_and_sw_cache_are_present(isolated):
    c,_,_=isolated
    for path in ['design.css','icons.mjs','catalog.mjs','public.mjs','admin.mjs']:
        assert c.get('/assets/'+path).status_code==200
        assert '/assets/'+path in c.get('/sw.js').text
    assert 'px-shell-v09' in c.get('/sw.js').text

def test_start_scripts_quote_paths_and_no_privileged_bypass():
    raw=(ROOT/'Start-Windows.cmd').read_bytes()
    assert b'\r\n' in raw and b'pushd "%~dp0"' in raw
    assert b'ExecutionPolicy' not in raw and b'RunAs' not in raw
    assert 'host' not in raw.decode().lower()

def test_port_detector_does_not_kill_other_processes():
    import socket
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));s.listen()
        assert not launcher.available_port(s.getsockname()[1])

def test_backup_consistency_and_no_credentials(tmp_path,monkeypatch):
    monkeypatch.setattr(backup_local,'ROOT',tmp_path);monkeypatch.delenv('DATABASE_URL',raising=False)
    (tmp_path/'data').mkdir()
    with sqlite3.connect(tmp_path/'data/pulsex-pilot.sqlite3') as c:
        c.execute('create table example(id integer primary key, text text)')
        c.execute('insert into example(text) values(?)',('بيانات Unicode',))
    (tmp_path/'data/first-run-accounts.json').write_text('DO_NOT_INCLUDE',encoding='utf-8')
    archive=backup_local.backup()
    with zipfile.ZipFile(archive) as z:
        assert 'data/first-run-accounts.json' not in z.namelist()
        z.extract('data/pulsex-pilot.sqlite3',tmp_path/'restore')
    with sqlite3.connect(tmp_path/'restore/data/pulsex-pilot.sqlite3') as c:
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert c.execute('select text from example').fetchone()[0]=='بيانات Unicode'
