from __future__ import annotations
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse, json, os, socket, subprocess, sys, tempfile, threading, time, urllib.request, uuid
import httpx, psutil

ROOT=Path(__file__).resolve().parents[1]
PROFILES={
    'pilot':   {'reads':1000,  'read_workers':50,  'writes':1000,  'write_workers':8,  'batch':25},
    'x5':      {'reads':1000,  'read_workers':50,  'writes':5000,  'write_workers':12, 'batch':50},
    'x10':     {'reads':1000,  'read_workers':50,  'writes':10000, 'write_workers':16, 'batch':50},
    'stretch': {'reads':1000, 'read_workers':50, 'writes':25000, 'write_workers':24, 'batch':50},
}
_tls=threading.local()

def pct(v,p):
    v=sorted(v); return v[max(0,min(len(v)-1,int(len(v)*p)-1))]

def client(base,timeout=30):
    c=getattr(_tls,'client',None)
    if c is None:
        c=httpx.Client(base_url=base,timeout=timeout,limits=httpx.Limits(max_keepalive_connections=8,max_connections=16))
        _tls.client=c
    return c

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--profile',choices=PROFILES,default='x5'); ap.add_argument('--output',default='')
    args=ap.parse_args(); cfg=PROFILES[args.profile]
    with tempfile.TemporaryDirectory(prefix='px-load-') as td:
        temp=Path(td)
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env={**os.environ,'HOST':'127.0.0.1','PORT':str(port),'PUBLIC_ORIGIN':base,'DATABASE_URL':'sqlite:///'+str(temp/'db.sqlite'),'CREDENTIALS_PATH':str(temp/'accounts.json'),'MEDIA_DIR':str(temp/'media'),'SEED_DEMO':'true','WEB_WORKERS':'1'}
        log=open(temp/'server.log','w',encoding='utf-8')
        proc=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=env,stdout=log,stderr=log)
        try:
            for _ in range(150):
                try: urllib.request.urlopen(base+'/api/health',timeout=.3); break
                except Exception: time.sleep(.1)
            else: raise RuntimeError('server timeout')
            process=psutil.Process(proc.pid); cpu0=process.cpu_times(); rss0=process.memory_info().rss
            read_lat=[]; read_errors=0
            def read_one(_):
                t=time.perf_counter()
                try: r=client(base).get('/api/public/site/agency-01');ok=r.status_code==200
                except Exception: ok=False
                return time.perf_counter()-t,ok
            t0=time.perf_counter()
            with ThreadPoolExecutor(max_workers=cfg['read_workers']) as pool:
                for latency,ok in pool.map(read_one,range(cfg['reads'])):
                    read_lat.append(latency); read_errors += 0 if ok else 1
            read_elapsed=time.perf_counter()-t0

            def item(i):
                return {'id':str(uuid.uuid4()),'site_id':f'agency-{1+i%10:02}','version':1,'kind':'survey','visitor_id':str(uuid.uuid4()),'session_id':str(uuid.uuid4()),'source':'web','target':'main','payload':{'answers':{'q-interest':'o1','q-rate':5}},'client_time':'2026-09-29T12:00:00+03:00'}
            items=[item(i) for i in range(cfg['writes'])]; b=cfg['batch']; batches=[items[i:i+b] for i in range(0,len(items),b)]
            write_lat=[];write_errors=0
            def send(batch):
                t=time.perf_counter()
                try:
                    r=client(base,60).post('/api/collect',json={'items':batch});ok=r.status_code==200 and all(x['status']=='accepted' for x in r.json()['receipts'])
                except Exception:ok=False
                return time.perf_counter()-t,ok
            t1=time.perf_counter()
            with ThreadPoolExecutor(max_workers=cfg['write_workers']) as pool:
                for latency,ok in pool.map(send,batches):
                    write_lat.append(latency);write_errors += 0 if ok else 1
            write_elapsed=time.perf_counter()-t1
            cpu1=process.cpu_times(); rss1=process.memory_info().rss
            report={
                'status':'passed' if read_errors==0 and write_errors==0 else 'failed',
                'profile':args.profile,'profile_config':cfg,'backend':'SQLite','server_workers':1,
                'not_production_capacity_certificate':True,
                'reads':{'requests':cfg['reads'],'workers':cfg['read_workers'],'errors':read_errors,'elapsed_s':round(read_elapsed,3),'rps':round(cfg['reads']/read_elapsed,1),'p50_s':round(pct(read_lat,.50),4),'p95_s':round(pct(read_lat,.95),4),'p99_s':round(pct(read_lat,.99),4)},
                'writes':{'submissions':cfg['writes'],'batch_size':b,'concurrent_clients':cfg['write_workers'],'errors':write_errors,'elapsed_s':round(write_elapsed,3),'submissions_per_s':round(cfg['writes']/write_elapsed,1),'batch_p50_s':round(pct(write_lat,.50),4),'batch_p95_s':round(pct(write_lat,.95),4),'batch_p99_s':round(pct(write_lat,.99),4)},
                'resource':{'rss_mb_before':round(rss0/1024/1024,1),'rss_mb_after':round(rss1/1024/1024,1),'rss_growth_mb':round((rss1-rss0)/1024/1024,1),'cpu_user_s':round(cpu1.user-cpu0.user,2),'cpu_system_s':round(cpu1.system-cpu0.system,2)},
                'limitations':['SQLite','single Uvicorn process','localhost','synthetic data','not simultaneous human browser sessions','no Redis/WebSocket/PostgreSQL/network latency']
            }
        finally:
            proc.terminate();
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: proc.kill();proc.wait()
            log.close()
    out=Path(args.output) if args.output else ROOT/f'qa/hardening/load-{args.profile}.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    if report['status']!='passed': raise SystemExit(1)
if __name__=='__main__':main()
