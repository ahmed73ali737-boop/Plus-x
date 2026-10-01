from __future__ import annotations
from pathlib import Path
import json, os, socket, subprocess, sys, tempfile, time, urllib.request
import httpx

ROOT=Path(__file__).resolve().parents[1]
checks=[]

def main():
    with tempfile.TemporaryDirectory(prefix='px-sec-') as td:
        temp=Path(td)
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env={**os.environ,'HOST':'127.0.0.1','PORT':str(port),'PUBLIC_ORIGIN':base,'DATABASE_URL':'sqlite:///'+str(temp/'db.sqlite'),'CREDENTIALS_PATH':str(temp/'accounts.json'),'MEDIA_DIR':str(temp/'media'),'SEED_DEMO':'true'}
        log=open(temp/'server.log','w',encoding='utf-8')
        proc=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try: urllib.request.urlopen(base+'/api/health',timeout=.3); break
                except Exception: time.sleep(.1)
            else: raise RuntimeError('server timeout')
            accounts=json.loads((temp/'accounts.json').read_text())
            with httpx.Client(base_url=base,timeout=20) as c:
                r=c.get('/api/health');
                assert r.headers['x-content-type-options']=='nosniff'; checks.append('security_headers')
                assert r.headers['cache-control']=='no-store'; checks.append('api_no_store')
                assert c.get('/api/admin/sites').status_code==401; checks.append('unauth_admin_denied')
                assert c.post('/api/access-request',json={'site_id':'platform','name':'x','email':'x@example.com'},headers={'Origin':'https://evil.example'}).status_code==403; checks.append('cross_origin_write_denied')
                user=accounts[2]; login=c.post('/api/auth/login',json={'email':user['email'],'password':user['password']}); assert login.status_code==200
                csrf=login.json()['csrf']
                assert c.get('/api/admin/sites/agency-02').status_code==403; checks.append('idor_scope_denied')
                site=c.get('/api/admin/sites/agency-01').json()
                assert c.put('/api/admin/sites/agency-01',json={'draft_rev':site['draft_rev'],'config':site['draft']}).status_code==403; checks.append('csrf_missing_denied')
                assert c.put('/api/admin/sites/agency-01',json={'draft_rev':site['draft_rev'],'config':site['draft']},headers={'X-CSRF':csrf}).status_code==200; checks.append('csrf_valid_allowed')
                created=c.post('/api/admin/sites/agency-01/devices',json={'name':'Security Tablet','device_type':'tablet'},headers={'X-CSRF':csrf}); assert created.status_code==200
                listed=c.get('/api/admin/sites/agency-01/devices').json()['devices']; assert listed and all('token_hash' not in x and 'device_token' not in x for x in listed); checks.append('device_secret_not_exposed')
                assert c.post('/api/device/heartbeat',json={'pending_count':0},headers={'X-PulseX-Device-Token':'invalid'}).status_code==401; checks.append('invalid_device_token_denied')
                r=c.get('/media/%2e%2e%2Fapp%2Fserver.py'); assert b'def create_app' not in r.content; checks.append('media_traversal_no_file_disclosure')
                r=c.get('/templates/%2e%2e%2Fapp%2Fserver.py'); assert b'def create_app' not in r.content; checks.append('template_traversal_no_file_disclosure')
                # Oversized body is rejected before route execution.
                payload='x'*(7*1024*1024+1)
                rr=c.post('/api/access-request',content=payload,headers={'Content-Type':'application/json','Origin':base})
                assert rr.status_code==413; checks.append('request_size_limit')
            # Fresh client/IP bucket equivalent is not available, but failed auth rate limit is checked in isolation.
            with httpx.Client(base_url=base,timeout=10) as c2:
                statuses=[c2.post('/api/auth/login',json={'email':'none@example.com','password':'not-the-right-password'}).status_code for _ in range(21)]
                assert statuses[-1]==429 and 429 in statuses and statuses.count(401)>=18; checks.append('auth_rate_limit')
            report={'status':'passed','passed':len(checks),'checks':checks,'backend':'SQLite','scope':'bounded hardening checks; not DAST or pentest'}
        finally:
            proc.terminate(); proc.wait(timeout=10); log.close()
    out=ROOT/'qa/hardening/security-smoke.json';out.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))

if __name__=='__main__': main()
