from __future__ import annotations
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import json, os, socket, subprocess, sys, tempfile, time, urllib.request, uuid, statistics
import httpx, psutil

ROOT=Path(__file__).resolve().parents[1]

def percentile(values,p):
    values=sorted(values)
    return values[max(0,min(len(values)-1,int(len(values)*p)-1))]

def main():
    with tempfile.TemporaryDirectory(prefix='px-cap-') as td:
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
            process=psutil.Process(proc.pid)
            # Concurrent public reads.
            read_lat=[]; read_errors=0
            def read_one(_):
                t=time.perf_counter()
                try:
                    with httpx.Client(base_url=base,timeout=15) as c:r=c.get('/api/public/site/agency-01'); ok=r.status_code==200
                except Exception: ok=False
                return time.perf_counter()-t,ok
            t0=time.perf_counter()
            with ThreadPoolExecutor(max_workers=50) as pool:
                for latency,ok in pool.map(read_one,range(1000)):
                    read_lat.append(latency); read_errors += 0 if ok else 1
            read_elapsed=time.perf_counter()-t0
            # Write bursts in batches, matching supported offline sync envelope limits.
            def item(i):
                return {'id':str(uuid.uuid4()),'site_id':f'agency-{1+i%10:02}','version':1,'kind':'survey','visitor_id':str(uuid.uuid4()),'session_id':str(uuid.uuid4()),'source':'web','target':'main','payload':{'answers':{'q-interest':'o1','q-rate':5}},'client_time':'2026-09-29T12:00:00+03:00'}
            all_items=[item(i) for i in range(1000)]; batches=[all_items[i:i+25] for i in range(0,1000,25)]
            write_lat=[]; write_errors=0
            def send(batch):
                t=time.perf_counter()
                try:
                    with httpx.Client(base_url=base,timeout=30) as c:
                        r=c.post('/api/collect',json={'items':batch});ok=r.status_code==200 and all(x['status']=='accepted' for x in r.json()['receipts'])
                except Exception:ok=False
                return time.perf_counter()-t,ok
            t1=time.perf_counter()
            with ThreadPoolExecutor(max_workers=8) as pool:
                for latency,ok in pool.map(send,batches):
                    write_lat.append(latency); write_errors += 0 if ok else 1
            write_elapsed=time.perf_counter()-t1
            rss=process.memory_info().rss
            report={
                'status':'passed' if read_errors==0 and write_errors==0 else 'failed',
                'backend':'SQLite','server_workers':1,'not_production_capacity_certificate':True,
                'reads':{'requests':1000,'workers':50,'errors':read_errors,'elapsed_s':round(read_elapsed,3),'rps':round(1000/read_elapsed,1),'p50_s':round(percentile(read_lat,.50),4),'p95_s':round(percentile(read_lat,.95),4),'p99_s':round(percentile(read_lat,.99),4)},
                'writes':{'submissions':1000,'batch_size':25,'concurrent_clients':8,'errors':write_errors,'elapsed_s':round(write_elapsed,3),'submissions_per_s':round(1000/write_elapsed,1),'batch_p95_s':round(percentile(write_lat,.95),4)},
                'server_rss_mb_after':round(rss/1024/1024,1),
                'limitations':['SQLite','single Uvicorn process','localhost','synthetic data','not 1000 simultaneous human sessions','no WebSocket/Redis/PostgreSQL']
            }
        finally:
            proc.terminate(); proc.wait(timeout=10);log.close()
    out=ROOT/'qa/hardening/capacity-smoke.json';out.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    if report['status']!='passed': raise SystemExit(1)

if __name__=='__main__': main()
