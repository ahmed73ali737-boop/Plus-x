from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json, os, statistics, sys, time, uuid
from fastapi.testclient import TestClient
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.server import create_app
url=os.environ.get('PX_POSTGRES_TEST_URL','')
if not url.startswith('postgresql+psycopg://'): raise SystemExit('POSTGRES_TEST_URL_REQUIRED')
app=create_app(url,origin='http://testserver',seed_demo=True)
with TestClient(app) as c:
    site=c.get('/api/public/site/agency-09')
    assert site.status_code==200
    version=site.json()['version']
def pct(xs,p):
    xs=sorted(xs); return xs[max(0,min(len(xs)-1,int((len(xs)-1)*p)))]
def read_one(_):
    t=time.perf_counter()
    try:
        with TestClient(app) as c: ok=c.get('/api/public/site/agency-09').status_code==200
    except Exception: ok=False
    return time.perf_counter()-t,ok
read_lat=[]; read_errors=0; t0=time.perf_counter()
with ThreadPoolExecutor(max_workers=32) as pool:
    for lat,ok in pool.map(read_one,range(1000)): read_lat.append(lat); read_errors+=0 if ok else 1
read_elapsed=time.perf_counter()-t0
def item():
    return {'id':str(uuid.uuid4()),'site_id':'agency-09','version':version,'kind':'survey','visitor_id':str(uuid.uuid4()),'session_id':str(uuid.uuid4()),'source':'web','target':'main','payload':{'answers':{'q-interest':'o1','q-rate':5}},'client_time':'2026-10-06T09:00:00+03:00'}
items=[item() for _ in range(1000)]; batches=[items[i:i+25] for i in range(0,1000,25)]
def write_one(batch):
    t=time.perf_counter()
    try:
        with TestClient(app) as c:
            r=c.post('/api/collect',json={'items':batch}); receipts=r.json().get('receipts',[]) if r.status_code==200 else []
            ok=len(receipts)==len(batch) and all(x.get('status')=='accepted' for x in receipts)
    except Exception: ok=False
    return time.perf_counter()-t,ok
write_lat=[]; write_errors=0; t1=time.perf_counter()
with ThreadPoolExecutor(max_workers=8) as pool:
    for lat,ok in pool.map(write_one,batches): write_lat.append(lat); write_errors+=0 if ok else 1
write_elapsed=time.perf_counter()-t1
report={'status':'passed' if not read_errors and not write_errors else 'failed','database':'PostgreSQL','not_production_capacity_certificate':True,'reads':{'requests':1000,'workers':32,'errors':read_errors,'rps':round(1000/read_elapsed,1),'p50_s':round(statistics.median(read_lat),4),'p95_s':round(pct(read_lat,.95),4),'p99_s':round(pct(read_lat,.99),4)},'writes':{'submissions':1000,'batch_size':25,'concurrent_clients':8,'errors':write_errors,'submissions_per_s':round(1000/write_elapsed,1),'batch_p50_s':round(statistics.median(write_lat),4),'batch_p95_s':round(pct(write_lat,.95),4),'batch_p99_s':round(pct(write_lat,.99),4)},'limitations':['in-process TestClient','single CI process','synthetic traffic','not production SLO evidence']}
(ROOT/'qa/postgres-capacity-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
if report['status']!='passed': raise SystemExit(1)
