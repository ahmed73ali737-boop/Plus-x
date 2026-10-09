"""Native PostgreSQL capacity smoke with ONE application lifespan.

Never create 1000 concurrent TestClient lifespans against one FastAPI app:
each lifespan disposes the same shared engine and can exhaust PostgreSQL.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json, os, statistics, sys, time, uuid
from fastapi.testclient import TestClient

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.server import create_app

def pct(values,p):
    values=sorted(values)
    return values[max(0,min(len(values)-1,int((len(values)-1)*p)))]

def run():
    url=os.environ.get("PX_POSTGRES_TEST_URL","")
    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError("POSTGRES_TEST_URL_REQUIRED")
    app=create_app(url,origin="http://testserver",seed_demo=True)
    with TestClient(app) as client:
        site=client.get("/api/public/site/easy")
        assert site.status_code==200,site.text[:200]
        version=site.json()["version"]

        def read_one(_):
            start=time.perf_counter()
            try:
                response=client.get("/api/public/site/easy")
                return time.perf_counter()-start,response.status_code==200
            except Exception:
                return time.perf_counter()-start,False

        t0=time.perf_counter()
        with ThreadPoolExecutor(max_workers=32) as pool:
            reads=list(pool.map(read_one,range(1000)))
        read_elapsed=max(time.perf_counter()-t0,0.001)
        read_errors=sum(not success for _,success in reads)
        read_lat=[delta for delta,_ in reads]

        def item():
            return {"id":str(uuid.uuid4()),"site_id":"agency-09","version":version,
                    "kind":"survey","visitor_id":str(uuid.uuid4()),
                    "session_id":str(uuid.uuid4()),"source":"web","target":"main",
                    "payload":{"answers":{"q-interest":"o1","q-rate":5}},
                    "client_time":"2026-10-06T09:00:00+03:00"}
        items=[item() for _ in range(1000)]
        batches=[items[i:i+25] for i in range(0,len(items),25)]

        def write_one(batch):
            start=time.perf_counter()
            try:
                response=client.post("/api/collect",json={"items":batch})
                receipts=response.json().get("receipts",[]) if response.status_code==200 else []
                ok=len(receipts)==len(batch) and all(x.get("status")=="accepted" for x in receipts)
                return time.perf_counter()-start,ok
            except Exception:
                return time.perf_counter()-start,False

        t1=time.perf_counter()
        with ThreadPoolExecutor(max_workers=8) as pool:
            writes=list(pool.map(write_one,batches))
        write_elapsed=max(time.perf_counter()-t1,0.001)
        write_errors=sum(not success for _,success in writes)
        write_lat=[delta for delta,_ in writes]

    report={
        "status":"passed" if not read_errors and not write_errors else "failed",
        "database":"PostgreSQL",
        "not_production_capacity_certificate":True,
        "app_lifespan_count":1,
        "reads":{"requests":len(reads),"workers":32,"errors":read_errors,
                 "rps":round(len(reads)/read_elapsed,1),
                 "p50_s":round(statistics.median(read_lat),4),
                 "p95_s":round(pct(read_lat,.95),4),
                 "p99_s":round(pct(read_lat,.99),4)},
        "writes":{"submissions":len(items),"batch_size":25,"concurrent_clients":8,
                  "errors":write_errors,"submissions_per_s":round(len(items)/write_elapsed,1),
                  "batch_p50_s":round(statistics.median(write_lat),4),
                  "batch_p95_s":round(pct(write_lat,.95),4),
                  "batch_p99_s":round(pct(write_lat,.99),4)},
        "limitations":["in-process TestClient","single CI process","synthetic traffic",
                       "not production SLO evidence"]
    }
    (ROOT/"qa").mkdir(exist_ok=True)
    (ROOT/"qa/postgres-capacity-smoke.json").write_text(
        json.dumps(report,indent=2),encoding="utf-8")
    print(json.dumps(report))
    return 0 if report["status"]=="passed" else 1

if __name__=="__main__":
    raise SystemExit(run())
