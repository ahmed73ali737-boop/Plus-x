from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json, statistics, sys, tempfile, time
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.server import create_app
from app.infrastructure.seed import seed_demo_data

with tempfile.TemporaryDirectory(prefix='px-expo-scale-') as td:
    db='sqlite:///'+str(Path(td)/'scale.sqlite')
    app=create_app(db,origin='http://testserver',seed_demo=False)
    seed_demo_data(app.state.engine,count=70)
    with TestClient(app) as c:
        event=c.get('/api/public/site/demo')
        assert event.status_code==200
        body=event.json()
        assert len(body['agencies'])==70,len(body['agencies'])
        slugs={row['slug'] for row in body['agencies']}
        assert 'tharawat' in slugs and 'easy' in slugs and 'rts' in slugs
    slugs=[{8:'tharawat',9:'easy',10:'rts'}.get(i,f'agency-{i:02}') for i in range(1,71)]
    def one(slug):
        t=time.perf_counter()
        with TestClient(app) as client:
            r=client.get('/api/public/site/'+slug)
            return time.perf_counter()-t,r.status_code==200 and r.json()['slug']==slug
    t0=time.perf_counter(); lat=[]; errors=0
    with ThreadPoolExecutor(max_workers=20) as pool:
        for d,ok in pool.map(one,slugs*10):
            lat.append(d); errors+=0 if ok else 1
    elapsed=time.perf_counter()-t0
    ordered=sorted(lat)
    def pct(p): return ordered[max(0,min(len(ordered)-1,int((len(ordered)-1)*p)))]
    report={'status':'passed' if errors==0 else 'failed','entities':70,'agency_bundle_requests':len(lat),'concurrent_clients':20,'errors':errors,'elapsed_s':round(elapsed,3),'rps':round(len(lat)/elapsed,1),'p50_s':round(statistics.median(lat),4),'p95_s':round(pct(.95),4),'p99_s':round(pct(.99),4),'backend':'SQLite','not_production_capacity_certificate':True,'purpose':'Verify the exhibition topology supports the target 70 participating entities without truncation and can serve repeated agency bundles.'}
    (ROOT/'qa/exhibition-scale-smoke.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
    if report['status']!='passed': raise SystemExit(1)
