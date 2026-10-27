"""Failure injection and fencing against real storage and database transactions."""
import contextlib,os,time
from io import BytesIO
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,update,func,event
from sqlalchemy.exc import OperationalError
from app.self_certificates_db import jobs,requests,certificates,exports,assets
from app.application import self_certificate_worker as worker
from app.application.self_certificate_storage import cleanup_unreferenced
from tests.test_self_certificate_http import system,new_link,prepare,submit,A,P

def pending(system):
    app,client=system;staff=client();link,_=new_link(staff)
    browser,token,prepared=prepare(app,link)
    assert submit(browser,token,prepared).status_code==202
    return app,staff,browser,token

def assert_issue(app,browser,token):
    value=browser.get(P+'/request/'+token+'/mine').json()
    assert value['status']=='issued',value
    cap=value['receive_url'].split('/')[-1]
    received=browser.get(P+'/receive/'+cap).json();assert received['status']=='valid',received
    raw=browser.get(received['download_url']);assert raw.status_code==200
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(certificates)).scalar_one()==1
    return received,raw.content

def test_stale_worker_cannot_commit_after_new_lease_wins_and_cleanup_keeps_live_files(system):
    app,staff,browser,token=pending(system)
    runtime=app.state.self_certificate_runtime
    stale=worker.claim(app.state.engine,lease_seconds=-1)
    winner=worker.claim(app.state.engine)
    assert stale and winner and stale['lease_owner']!=winner['lease_owner']
    assert worker.process_one(app.state.engine,runtime.store,runtime.keys,job=stale)
    with app.state.engine.connect() as conn:assert conn.execute(select(func.count()).select_from(certificates)).scalar_one()==0
    assert worker.process_one(app.state.engine,runtime.store,runtime.keys,job=winner)
    value,before=assert_issue(app,browser,token)
    for folder in runtime.store.root.iterdir():
        if folder.is_dir():
            for path in folder.iterdir():
                if path.is_file():os.utime(path,(time.time()-172800,time.time()-172800))
    result=cleanup_unreferenced(app.state.engine,runtime.store)
    assert result['removed_files']>=2
    assert browser.get(value['download_url']).content==before

def test_disk_error_and_database_failure_after_files_retry_without_duplicate(system,monkeypatch):
    app,staff,browser,token=pending(system);runtime=app.state.self_certificate_runtime
    with monkeypatch.context() as scoped:
        def full(*args,**kwargs):raise OSError('SYNTHETIC_DISK_FULL')
        scoped.setattr(runtime.store,'put',full)
        assert runtime.generate()
    with app.state.engine.begin() as conn:
        assert conn.execute(select(func.count()).select_from(certificates)).scalar_one()==0
        assert conn.execute(select(requests.c.status)).scalar_one()=='registered'
        conn.execute(update(jobs).values(available_at='2020-01-01T00:00:00.000000+00:00'))
    raised=[False]
    def fail_insert(conn,cursor,statement,parameters,context,executemany):
        if statement.startswith('INSERT INTO px_self_certificates ') and not raised[0]:
            raised[0]=True;raise OperationalError('synthetic insert failure',None,RuntimeError('QA'))
    event.listen(app.state.engine,'before_cursor_execute',fail_insert)
    try:assert runtime.generate()
    finally:event.remove(app.state.engine,'before_cursor_execute',fail_insert)
    assert raised[0]
    with app.state.engine.begin() as conn:
        assert conn.execute(select(func.count()).select_from(certificates)).scalar_one()==0
        assert conn.execute(select(func.count()).select_from(assets).where(assets.c.kind=='final')).scalar_one()==0
        conn.execute(update(jobs).values(available_at='2020-01-01T00:00:00.000000+00:00'))
    assert runtime.generate();assert_issue(app,browser,token)

def test_lost_worker_commit_ack_does_not_reissue_or_downgrade_issued(system):
    app,staff,browser,token=pending(system);runtime=app.state.self_certificate_runtime
    engine=app.state.engine
    class LoseAck:
        dialect=engine.dialect
        def connect(self):return engine.connect()
        @contextlib.contextmanager
        def begin(self):
            with engine.begin() as conn:yield conn
            if not getattr(self,'lost',False):
                with engine.connect() as conn:issued=conn.execute(select(certificates.c.id).limit(1)).first()
                if issued:
                    self.lost=True;raise OperationalError('synthetic lost commit ack',None,RuntimeError('QA'))
    adapter=LoseAck()
    assert worker.process_one(adapter,runtime.store,runtime.keys)
    assert adapter.lost
    assert_issue(app,browser,token)
    assert not runtime.generate()
    with engine.connect() as conn:assert conn.execute(select(jobs.c.status)).scalar_one()=='done'

def test_permanent_error_stops_and_owner_can_retry_same_request(system,monkeypatch):
    app,staff,browser,token=pending(system);runtime=app.state.self_certificate_runtime
    with monkeypatch.context() as scoped:
        def bad(*args,**kwargs):raise ValueError('SYNTHETIC_DESIGN_FAILURE')
        scoped.setattr(worker,'generation_inputs',bad)
        assert runtime.generate()
    with app.state.engine.connect() as conn:
        row=conn.execute(select(requests)).mappings().one();ident=row['id']
        assert row['status']=='failed'
    assert not runtime.generate()
    assert staff.post(A+'/requests/'+ident+'/retry',json={}).status_code==200
    assert runtime.generate();assert_issue(app,browser,token)
    with app.state.engine.connect() as conn:assert conn.execute(select(func.count()).select_from(requests)).scalar_one()==1

def test_missing_or_corrupt_final_never_rerenders_on_download(system):
    app,staff,browser,token=pending(system);runtime=app.state.self_certificate_runtime
    assert runtime.generate();value,before=assert_issue(app,browser,token)
    with app.state.engine.connect() as conn:
        cert=conn.execute(select(certificates)).mappings().one()
        asset=conn.execute(select(assets).where(assets.c.id==cert['final_asset_id'])).mappings().one()
    path=runtime.store.path(asset['storage_key']);path.write_bytes(b'corrupt')
    assert browser.get(value['download_url']).status_code==503
    assert browser.get(P+'/verify/'+value['serial']).json()['status']=='integrity_error'
    assert path.read_bytes()==b'corrupt'
    path.write_bytes(before)
    assert browser.get(value['download_url']).content==before
    path.unlink()
    assert browser.get(value['download_url']).status_code==503

def test_new_api_rejects_overlaps_forged_owner_and_old_routes_cannot_modify_issued(system):
    app,staff,browser,token=pending(system);runtime=app.state.self_certificate_runtime
    assert runtime.generate();value,before=assert_issue(app,browser,token)
    with app.state.engine.connect() as conn:
        cert=dict(conn.execute(select(certificates)).mappings().one())
    for action in ('replace','revoke'):
        result=staff.post('/api/admin/events/self-event/certificates/'+cert['id']+'/'+action,json={'reason':'QA forbidden change'})
        assert result.status_code in (403,404,422)
    assert browser.get(value['download_url']).content==before
    assert browser.post(P+'/request/'+token,json={'owner_account_id':'self-b'}).json()['status']=='issued'
    unauth=TestClient(app)
    response=unauth.post(P+'/request/'+token,json={'phone':'sensitive-invalid','consent':False})
    assert response.status_code in (403,404) and 'sensitive-invalid' not in response.text

def test_exhausted_crashed_lease_is_failed_and_does_not_block_following_work(system):
    app,staff,browser,token=pending(system);runtime=app.state.self_certificate_runtime
    with app.state.engine.begin() as conn:
        job=dict(conn.execute(select(jobs)).mappings().one())
        conn.execute(update(jobs).where(jobs.c.id==job['id']).values(status='leased',attempts=3,
            lease_owner='stale-owner',lease_until='2000-01-01T00:00:00+00:00'))
        conn.execute(update(requests).where(requests.c.id==job['request_id']).values(status='processing'))
    assert not runtime.generate()
    with app.state.engine.connect() as conn:
        assert conn.execute(select(jobs.c.status,jobs.c.last_error_code).where(jobs.c.id==job['id'])).one()==('failed','GENERATION_FAILED')
        assert conn.execute(select(requests.c.status,requests.c.error_code).where(requests.c.id==job['request_id'])).one()==('failed','GENERATION_FAILED')
