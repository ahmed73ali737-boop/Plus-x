"""Real local HTTP API checks + bounded synthetic write workload; not browser E2E or a capacity certificate."""
from pathlib import Path
import os, subprocess, tempfile, json, time, urllib.request, sys, uuid, sqlite3
from concurrent.futures import ThreadPoolExecutor
import httpx
ROOT=Path(__file__).resolve().parents[1];temp=Path(tempfile.mkdtemp(prefix='px-http-'));port=4432;url=f'http://127.0.0.1:{port}'
env={**os.environ,'PORT':str(port),'PUBLIC_ORIGIN':url,'DATABASE_URL':'sqlite:///'+str(temp/'db.sqlite'),'CREDENTIALS_PATH':str(temp/'accounts.json'),'MEDIA_DIR':str(temp/'media')}
log=open(ROOT/'qa/http-server.log','w');proc=subprocess.Popen([sys.executable,'run.py'],cwd=ROOT,env=env,stdout=log,stderr=log)
try:
    for _ in range(80):
        try:urllib.request.urlopen(url+'/api/health',timeout=1);break
        except:time.sleep(.15)
    accounts=json.loads((temp/'accounts.json').read_text());checks=[]
    with httpx.Client(base_url=url,timeout=30) as c:
        assert c.get('/').status_code==200;assert c.get('/api/public/site/demo').status_code==200;checks.append('real_http_platform_and_event')
        u=accounts[2];r=c.post('/api/auth/login',json={'email':u['email'],'password':u['password']});assert r.status_code==200;c.headers['X-CSRF']=r.json()['csrf'];checks.append('real_http_cookie_login')
        assert c.get('/api/admin/sites/agency-02').status_code==403;checks.append('real_http_tenant_scope')
        assert c.get('/api/admin/sites/agency-01/qr').content.startswith(b'\x89PNG');checks.append('real_http_qr')
    def envelope(i):
        return {'id':str(uuid.uuid4()),'site_id':f'agency-{1+i%10:02}','version':1,'kind':'survey','visitor_id':str(uuid.uuid4()),'session_id':str(uuid.uuid4()),'source':'kiosk' if i%2 else 'web','target':'main','payload':{'answers':{'q-interest':'o1','q-note':'SYNTHETIC_HTTP_TEST','q-rate':5}},'client_time':'2026-09-28T15:00:00+03:00'}
    items=[envelope(i) for i in range(1000)];batches=[items[i:i+50] for i in range(0,len(items),50)]
    def submit(batch):
        start=time.monotonic()
        with httpx.Client(base_url=url,timeout=60) as c:
            r=c.post('/api/collect',json={'items':batch});assert r.status_code==200,r.text
            assert all(x['status']=='accepted' for x in r.json()['receipts']),r.text
        return time.monotonic()-start
    start=time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:durations=list(pool.map(submit,batches))
    elapsed=time.monotonic()-start;checks.append('1000_distinct_submissions_4_batch_clients')
    with httpx.Client(base_url=url,timeout=30) as c:
        # Simulate a client not retaining its receipt, then replay the identical body.
        r=c.post('/api/collect',json={'items':items[:50]});assert all(x['status']=='duplicate' for x in r.json()['receipts']);checks.append('replay_50_exact_bodies_no_extra_writes')
    conn=sqlite3.connect(temp/'db.sqlite');count=conn.execute("select count(*) from px_submissions where kind='survey'").fetchone()[0];assert count==1000;conn.close();checks.append('database_count_matches_1000')
    report={'checks':checks,'passed':len(checks),'backend':'SQLite','transport':'real local HTTP; Python clients, not browser','distinct_synthetic_submissions':1000,'batch_size':50,'concurrent_batch_clients':4,'elapsed_seconds':round(elapsed,3),'batch_request_p95_seconds':round(sorted(durations)[int(.95*len(durations))-1],3),'data_loss':0,'extra_rows_after_replay':0,'not_a_concurrent_1000_user_or_postgresql_benchmark':True,'not_physical_kiosk_test':True}
    (ROOT/'qa/http-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report))
finally:proc.terminate();proc.wait(timeout=10);log.close()
