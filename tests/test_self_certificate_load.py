"""Opt-in isolated end-to-end load rehearsal; never targets a configured service."""
import os,secrets,time
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select,func
from app.self_certificates_db import requests,jobs,certificates,exports
from tests.test_self_certificate_http import A,P,system,new_link,new_model

@pytest.mark.skipif(os.environ.get('RUN_CERTIFICATE_LOAD')!='1000',reason='isolated 1000 participant rehearsal is opt-in')
def test_1000_distributed_participant_requests_issue_once_and_export_concurrently(system):
    rehearsal_started=time.perf_counter()
    deadline=rehearsal_started+240
    app,client=system
    if os.environ.get('CERTIFICATE_TEST_POSTGRES')!='true':pytest.skip('load rehearsal requires isolated PostgreSQL')
    staff=client();model=new_model(staff,'نموذج حمل اصطناعي')
    links=[new_link(staff,model)[0] for _ in range(20)]
    count=1000;workers=20;per_worker=count//workers
    def submit_batch(worker_id):
        timings=[]
        browser=TestClient(app)
        for i in range(per_worker):
            number=worker_id*per_worker+i;link=links[number%len(links)]
            browser.cookies.clear();seed=secrets.token_hex(32)
            token=link['request_url'].rsplit('/',1)[-1]
            prepared=browser.post(P+'/request/'+token+'/prepare',json={'browser_seed':seed})
            assert prepared.status_code==200,prepared.text
            began=time.perf_counter()
            response=browser.post(P+'/request/'+token,json={
                'name':'مشارك اختبار الحمل','phone':'0770123456','consent':True,
                'request_nonce':prepared.json()['request_nonce']})
            elapsed=time.perf_counter()-began
            assert response.status_code==202,response.text
            timings.append(elapsed)
        browser.close()
        return timings

    start=time.perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        batches=list(pool.map(submit_batch,range(workers),timeout=max(1,deadline-time.perf_counter())))
    all_times=sorted(value for batch in batches for value in batch)
    registration_seconds=time.perf_counter()-start
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(requests)).scalar_one()==count
        assert conn.execute(select(func.count()).select_from(jobs)).scalar_one()==count

    export_response=staff.post(A+'/exports',json={'format':'csv'})
    assert export_response.status_code==200,export_response.text
    created=export_response.json()
    generation_workers=6
    with ThreadPoolExecutor(max_workers=generation_workers+1) as pool:
        export_future=pool.submit(app.state.self_certificate_runtime.export)
        issue_futures=[pool.submit(_drain,app) for _ in range(generation_workers)]
        remaining=max(1,deadline-time.perf_counter())
        assert export_future.result(timeout=remaining)
        issued=[future.result(timeout=max(1,deadline-time.perf_counter())) for future in issue_futures]
    assert sum(issued)==count
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(certificates)).scalar_one()==count
        assert conn.execute(select(func.count()).select_from(jobs).where(jobs.c.status=='done')).scalar_one()==count
        assert conn.execute(select(exports.c.status).where(exports.c.id==created['id'])).scalar_one()=='done'
        assert conn.execute(select(func.count()).select_from(certificates).group_by(certificates.c.request_id).having(func.count()>1)).first() is None
    p95=all_times[int(.95*(len(all_times)-1))]
    total_seconds=time.perf_counter()-rehearsal_started
    assert p95<2.0,f'P95_SUBMIT_SECONDS={p95:.3f}'
    assert total_seconds<240,f'TOTAL_REHEARSAL_SECONDS={total_seconds:.1f}'
    # A compact result is written by pytest's junit record and test report; no participant data is emitted.
    print({'requests':count,'workers':workers,'links':len(links),'registration_seconds':round(registration_seconds,3),
        'submit_p95_seconds':round(p95,4),'generation_workers':len(issued),'issued':sum(issued),
        'total_seconds':round(total_seconds,3),'export':'done'})

def _drain(app):
    count=0
    while app.state.self_certificate_runtime.generate():count+=1
    return count
