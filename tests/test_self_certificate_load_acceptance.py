"""Opt-in monotonic end-to-end load acceptance with durable failure/deadline evidence."""
import json,os,secrets,threading,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,func,text
from app.self_certificates_db import requests,jobs,certificates,exports,assets
from app.application import self_certificate_metrics as metrics
from tests.test_self_certificate_http import system,new_link,new_model,A,P

@pytest.mark.skipif(os.environ.get('RUN_CERTIFICATE_LOAD')!='1000',reason='Explicit isolated load rehearsal required')
def test_distributed_participant_load_with_request_snapshot_and_final_assets(system):
    if os.environ.get('CERTIFICATE_TEST_POSTGRES')!='true':pytest.skip('Dedicated PostgreSQL required')
    import resource
    app,client=system
    count=int(os.environ.get('CERTIFICATE_LOAD_COUNT','1000'))
    if count not in (20,100,1000,1020):raise RuntimeError('LOAD_COUNT_INVALID')
    report_path=Path(os.environ['CERTIFICATE_LOAD_REPORT'])
    report={'status':'running','count':count,'links':20,'submitters':20,'generation_workers':6,
        'dimensions':[1200,800],'scenario_deadline_seconds':240,'cpu_limit':4,'memory_limit_gib':4}
    started=time.perf_counter();deadline=started+240
    report_lock=threading.Lock()
    def persist():
        with report_lock:
            temporary=report_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            temporary.replace(report_path)
    def counts():
        with app.state.engine.begin() as conn:
            conn.exec_driver_sql("SET LOCAL statement_timeout='2000ms'")
            return {'requests':conn.execute(select(func.count()).select_from(requests)).scalar_one(),
                'issued':conn.execute(select(func.count()).select_from(certificates)).scalar_one(),
                'done_jobs':conn.execute(select(func.count()).select_from(jobs).where(jobs.c.status=='done')).scalar_one(),
                'exports_done':conn.execute(select(func.count()).select_from(exports).where(exports.c.status=='done')).scalar_one(),
                'duplicates':len(conn.execute(select(certificates.c.request_id).group_by(certificates.c.request_id).having(func.count()>1)).all())}
    def at_deadline():
        report['deadline_reached']=True
        report['status']='incomplete_at_240_seconds'
        report['deadline_observed_elapsed']=time.perf_counter()-started
        try:report['deadline_counts']=counts()
        except Exception:report['deadline_counts_unavailable']=True
        persist()
    alarm=threading.Timer(240,at_deadline);alarm.daemon=True;alarm.start()
    persist()
    try:
        phase=time.perf_counter()
        staff=client();model=new_model(staff,'نموذج حمل اصطناعي')
        link_rows=[new_link(staff,model)[0] for _ in range(20)]
        report['setup_seconds']=time.perf_counter()-phase;persist()
        def submit_batch(worker):
            times=[]
            browser=TestClient(app);browser.headers.update({'Origin':'http://testserver'})
            try:
                for n in range(worker,count,20):
                    assert time.perf_counter()<deadline,'SCENARIO_DEADLINE'
                    browser.cookies.clear();token=link_rows[n%20]['request_url'].rsplit('/',1)[-1]
                    prepared=browser.post(P+'/request/'+token+'/prepare',json={'browser_seed':secrets.token_hex(32)})
                    assert prepared.status_code==200,prepared.text
                    began=time.perf_counter()
                    value=browser.post(P+'/request/'+token,json={'name':'مشارك اختبار الحمل','phone':'0770123456','consent':True,'request_nonce':prepared.json()['request_nonce']})
                    times.append(time.perf_counter()-began)
                    assert value.status_code==202,value.text
            finally:browser.close()
            return times
        phase=time.perf_counter()
        with ThreadPoolExecutor(max_workers=20) as pool:
            batches=list(pool.map(submit_batch,range(20),timeout=max(.1,deadline-time.perf_counter())))
        times=sorted(x for batch in batches for x in batch)
        report['registration_seconds']=time.perf_counter()-phase
        report['submit_p95_seconds']=times[int(.95*(len(times)-1))]
        report['after_registration']=counts();persist()
        response=staff.post(A+'/exports',json={'format':'csv','idempotency_key':'load-export-'+secrets.token_hex(16)})
        assert response.status_code==200,response.text
        assert response.json()['expected_rows']==count
        def drain():
            completed=0
            while time.perf_counter()<deadline and app.state.self_certificate_runtime.generate():completed+=1
            return completed
        phase=time.perf_counter()
        with ThreadPoolExecutor(max_workers=7) as pool:
            export=pool.submit(app.state.self_certificate_runtime.export)
            futures=[pool.submit(drain) for _ in range(6)]
            assert export.result(timeout=max(.1,deadline-time.perf_counter()))
            report['worker_jobs_processed']=[f.result(timeout=max(.1,deadline-time.perf_counter())) for f in futures]
        report['generation_seconds']=time.perf_counter()-phase
        actual=counts();report['final_counts']=actual
        assert actual==dict(requests=count,issued=count,done_jobs=count,exports_done=1,duplicates=0),actual
        phase=time.perf_counter()
        store=app.state.self_certificate_runtime.store
        with app.state.engine.connect() as conn:
            for asset in conn.execute(select(assets).where(assets.c.kind.in_(('final','thumbnail','export')))).mappings():
                store.verified_path(asset)
        report['asset_verification_seconds']=time.perf_counter()-phase
        report['total_seconds']=time.perf_counter()-started
        assert report['submit_p95_seconds']<2
        assert report['total_seconds']<240
        report['status']='passed'
    except BaseException as error:
        if report['status']!='incomplete_at_240_seconds':report['status']='failed'
        report['failure_kind']=type(error).__name__
        raise
    finally:
        alarm.cancel()
        report['observed_elapsed_seconds']=time.perf_counter()-started
        report['parent_max_rss_kib']=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report['stage_metrics']=metrics.snapshot()
        try:report['last_counts']=counts()
        except Exception:report['last_counts_unavailable']=True
        persist()
        print(json.dumps({k:v for k,v in report.items() if k!='stage_metrics'},ensure_ascii=False))
