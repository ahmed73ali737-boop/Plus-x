from __future__ import annotations
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse, json, os, socket, sqlite3, subprocess, sys, tempfile, time, urllib.request, uuid
from collections import Counter
from performance_support import classify_response, classify_exception
import httpx, psutil
from harness_support import ThreadClients, result_file, stop_process

ROOT=Path(__file__).resolve().parents[1]
PROFILES={
    'pilot':   {'reads':1000,  'read_workers':50,  'writes':1000,  'write_workers':8,  'batch':25},
    'x5':      {'reads':1000,  'read_workers':50,  'writes':5000,  'write_workers':12, 'batch':50},
    'x10':     {'reads':1000,  'read_workers':50,  'writes':10000, 'write_workers':16, 'batch':50},
    'stretch': {'reads':1000, 'read_workers':50, 'writes':25000, 'write_workers':24, 'batch':50},
}
def pct(v,p):
    v=sorted(v); return v[max(0,min(len(v)-1,int(len(v)*p)-1))]

def resources(pid):
    try:
        root=psutil.Process(pid)
        processes=[root,*root.children(recursive=True)]
    except (psutil.NoSuchProcess,psutil.AccessDenied) as error:
        return {'available':False,'reason':'PROCESS_TREE_UNAVAILABLE','exception_type':type(error).__name__}
    rss=cpu_user=cpu_system=0
    for process in processes:
        try:
            rss+=process.memory_info().rss
            cpu=process.cpu_times();cpu_user+=cpu.user;cpu_system+=cpu.system
        except psutil.NoSuchProcess:pass
    return {'available':True,'rss':rss,'cpu_user':cpu_user,'cpu_system':cpu_system,'processes':len(processes)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--profile',choices=PROFILES,default='x5'); ap.add_argument('--output',default='')
    args=ap.parse_args(); cfg=PROFILES[args.profile]
    out=Path(args.output) if args.output else ROOT/f'qa/hardening/load-{args.profile}.json'
    with result_file(out) as evidence, tempfile.TemporaryDirectory(prefix='px-load-') as td:
        clients=ThreadClients()
        temp=Path(td)
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        base=f'http://127.0.0.1:{port}'
        env={**os.environ,'HOST':'127.0.0.1','PORT':str(port),'PUBLIC_ORIGIN':base,'DATABASE_URL':'sqlite:///'+str(temp/'db.sqlite'),'CREDENTIALS_PATH':str(temp/'accounts.json'),'MEDIA_DIR':str(temp/'media'),'SEED_DEMO':'true','WEB_WORKERS':'1','PULSEX_ENV':'test','REQUIRE_POSTGRES':'false'}
        log=open(temp/'server.log','w',encoding='utf-8')
        proc=None
        try:
            proc=subprocess.Popen([sys.executable,str(ROOT/'run.py')],cwd=ROOT,env=env,stdout=log,stderr=log)
            for _ in range(150):
                try: urllib.request.urlopen(base+'/api/health',timeout=.3); break
                except Exception: time.sleep(.1)
            else: raise RuntimeError('server timeout')
            resource0=resources(proc.pid)
            read_classes=Counter();write_classes=Counter();receipt_statuses=Counter()
            read_lat=[]; read_errors=0
            def read_one(_):
                worker_client=clients.get(base)
                t=time.perf_counter()
                try:
                    with worker_client.stream('GET','/api/public/site/agency-01') as r:
                        r.read();category,_=classify_response(r)
                except Exception as error:category=classify_exception(error)
                return time.perf_counter()-t,category
            t0=time.perf_counter()
            with ThreadPoolExecutor(max_workers=cfg['read_workers']) as pool:
                for latency,category in pool.map(read_one,range(cfg['reads'])):
                    read_lat.append(latency);read_classes[category]+=1;read_errors+=category!='passed'
            read_elapsed=time.perf_counter()-t0

            def item(i):
                return {'id':str(uuid.uuid4()),'site_id':f'agency-{1+i%10:02}','version':1,'kind':'survey','visitor_id':str(uuid.uuid4()),'session_id':str(uuid.uuid4()),'source':'web','target':'main','payload':{'answers':{'q-interest':'o1','q-rate':5}},'client_time':'2026-09-29T12:00:00+03:00'}
            items=[item(i) for i in range(cfg['writes'])]; b=cfg['batch']; batches=[items[i:i+b] for i in range(0,len(items),b)]
            write_lat=[];write_errors=0
            def send(batch):
                worker_client=clients.get(base,60)
                t=time.perf_counter()
                try:
                    with worker_client.stream('POST','/api/collect',json={'items':batch}) as r:
                        r.read()
                        category,statuses=classify_response(r,len(batch))
                except Exception as error:category,statuses=classify_exception(error),Counter()
                return time.perf_counter()-t,category,statuses
            t1=time.perf_counter()
            with ThreadPoolExecutor(max_workers=cfg['write_workers']) as pool:
                for latency,category,statuses in pool.map(send,batches):
                    write_lat.append(latency);write_classes[category]+=1;receipt_statuses.update(statuses);write_errors+=category!='passed'
            write_elapsed=time.perf_counter()-t1
            resource1=resources(proc.pid)
            with sqlite3.connect((temp/'db.sqlite').as_uri()+'?mode=ro',uri=True) as db:
                persisted=db.execute('SELECT count(*) FROM px_submissions').fetchone()[0]
            report={
                'status':'passed' if read_errors==0 and write_errors==0 and persisted==cfg['writes'] else 'failed',
                'profile':args.profile,'profile_config':cfg,'backend':'SQLite','server_workers':1,
                'not_production_capacity_certificate':True,
                'reads':{'requests':cfg['reads'],'workers':cfg['read_workers'],'errors':read_errors,'elapsed_s':round(read_elapsed,3),'rps':round(cfg['reads']/read_elapsed,1),'p50_s':round(pct(read_lat,.50),4),'p95_s':round(pct(read_lat,.95),4),'p99_s':round(pct(read_lat,.99),4)},
                'writes':{'submissions':cfg['writes'],'batch_size':b,'concurrent_clients':cfg['write_workers'],'errors':write_errors,'elapsed_s':round(write_elapsed,3),'submissions_per_s':round(cfg['writes']/write_elapsed,1),'batch_p50_s':round(pct(write_lat,.50),4),'batch_p95_s':round(pct(write_lat,.95),4),'batch_p99_s':round(pct(write_lat,.99),4)},
                'classification':{'reads':dict(read_classes),'write_batches':dict(write_classes),'write_rows':dict(receipt_statuses),'unit':'HTTP requests / write batches / individual receipt rows are separate'},
                'persistence':{'expected_submissions':cfg['writes'],'actual_submissions':persisted,'matched':persisted==cfg['writes']},
                'slo_status':'not_defined','performance_accepted':False,
                'pool_wait_measurement':'not instrumented; PostgreSQL profiling required',
                'resource':{'scope':'sum of server launcher and recursive children; not container/host totals',
                            'before':resource0,'after':resource1},
                'limitations':['SQLite','single Uvicorn process','localhost','synthetic data','not simultaneous human browser sessions','no Redis/WebSocket/PostgreSQL/network latency']
            }
            evidence.update(report)
        finally:
            try:
                clients.close()
            finally:
                try:
                    if proc is not None:stop_process(proc)
                finally: log.close()
    out=Path(args.output) if args.output else ROOT/f'qa/hardening/load-{args.profile}.json';out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    if report['status']!='passed': raise SystemExit(1)
if __name__=='__main__':main()
