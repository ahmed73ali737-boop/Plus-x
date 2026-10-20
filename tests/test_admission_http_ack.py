"""Real HTTP commit followed by lost client ACK, using a disposable server/DB."""
from harness_support import sqlite_connection
from contextlib import contextmanager
from datetime import datetime
import json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path
from zoneinfo import ZoneInfo
import httpx
from harness_support import stop_process

ROOT=Path(__file__).resolve().parents[1]


@contextmanager
def running_server(temp):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    base=f'http://127.0.0.1:{port}'
    env={**os.environ,'HOST':'127.0.0.1','PORT':str(port),'PUBLIC_ORIGIN':base,
         'PULSEX_ENV':'test','REQUIRE_POSTGRES':'false','SEED_DEMO':'true','WEB_WORKERS':'1',
         'DATABASE_URL':'sqlite:///'+str(temp/'http.sqlite'),'MEDIA_DIR':str(temp/'media'),
         'CREDENTIALS_PATH':str(temp/'accounts.json')}
    with (temp/'server.log').open('w',encoding='utf-8') as log:
        proc=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            with httpx.Client(base_url=base,trust_env=False,timeout=5) as staff:
                for _ in range(100):
                    try:
                        if staff.get('/api/health/ready').status_code==200:break
                    except httpx.HTTPError:pass
                    if proc.poll() is not None:raise RuntimeError('QA server exited')
                    time.sleep(.1)
                else:raise RuntimeError('QA server startup timeout')
                yield base,staff
        finally:stop_process(proc)


def test_real_http_lost_ack_after_commit_has_one_ledger_use(tmp_path):
    with running_server(tmp_path) as (base,staff):
        admin=next(x for x in json.loads((tmp_path/'accounts.json').read_text()) if x['email']=='admin@pulsex.test')
        auth=staff.post('/api/auth/login',json={'email':admin['email'],'password':admin['password']});auth.raise_for_status()
        staff.headers.update({'X-CSRF':auth.json()['csrf'],'Origin':base})
        path='/api/admin/events/event-demo'
        day=datetime.now(ZoneInfo('Asia/Aden')).date().isoformat()
        p=staff.put(path+'/admission-policy',json={'enabled':True,'visibility':'private','registration_mode':'auto','entry_mode':'daily','max_companions':2,'days':[{'date':day,'capacity':10}]});p.raise_for_status()
        invite=staff.post(path+'/invitations',json={'name':'HTTP ACK QA','phone':'+967777993002','max_companions':2});invite.raise_for_status()
        token=invite.json()['token']
        issued=staff.post('/api/public/invitations/'+token+'/rsvp',json={'response':'accepted','consent':True,'companions':2,'days':[day]});issued.raise_for_status()
        body={'guest_number':issued.json()['guest_number'],'scan_id':'real-http-ack','mode':'entry','checkpoint':'main','quantity':2}
        class LoseCommittedResponse(httpx.HTTPTransport):
            def handle_request(self,request):
                response=super().handle_request(request)
                response.read()
                assert response.status_code==200
                assert json.loads(response.content)['status']=='accepted'
                response.close()
                raise httpx.ReadError('TEST_LOST_ACK_AFTER_COMMIT',request=request)
        import pytest
        with httpx.Client(base_url=base,transport=LoseCommittedResponse(),cookies=staff.cookies,headers=staff.headers,timeout=10) as dropping:
            with pytest.raises(httpx.ReadError,match='TEST_LOST_ACK_AFTER_COMMIT'):
                dropping.post(path+'/guest-checkins',json=body)
        replay=staff.post(path+'/guest-checkins',json=body)
        assert replay.status_code==200 and replay.json()['status']=='duplicate'
        with sqlite_connection(tmp_path/'http.sqlite') as db:
            assert db.execute('SELECT count(*) FROM px_guest_checkins WHERE id=?',(body['scan_id'],)).fetchone()[0]==1
            assert db.execute('SELECT count(*) FROM px_admission_uses WHERE scan_id=?',(body['scan_id'],)).fetchone()[0]==1
            assert db.execute('SELECT consumed FROM px_admission_entitlements').fetchone()[0]==2
