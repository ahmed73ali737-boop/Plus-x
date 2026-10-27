"""Targeted operations: stale export fencing, service health, and bounded large rasters."""
from pathlib import Path
from io import BytesIO
from datetime import datetime,timezone,timedelta
from concurrent.futures import ThreadPoolExecutor
import json,os,time,threading
import pytest
from sqlalchemy import select,update,func
from sqlalchemy.exc import DBAPIError
from fastapi import HTTPException
from PIL import Image
from app.application import self_certificate_worker as worker,self_certificate_exports as exporter
from app.application import self_certificate_rendering as renderer,self_certificate_branding as brand,self_certificate_fonts as fonts
from app.application.self_certificate_storage import CertificateStore
from app.self_certificates_db import exports,assets,requests,certificates
from tests.test_self_certificate_http import system,A,P,new_link,prepare,submit

def test_export_lost_lease_cannot_publish_partial_or_replace_winner(system,monkeypatch):
    app,clients=system;staff=clients();link,_=new_link(staff)
    browser,token,prepared=prepare(app,link)
    assert submit(browser,token,prepared).status_code==202
    job=staff.post(A+'/exports',json={'format':'csv'}).json()
    runtime=app.state.self_certificate_runtime
    original=runtime.store.put_file;claimed=[]
    def lose_lease(path):
        stored=original(path)
        with app.state.engine.begin() as conn:
            conn.execute(update(exports).where(exports.c.id==job['id']).values(lease_until='2000-01-01T00:00:00+00:00'))
        claimed.append(exporter.claim_export(app.state.engine))
        return stored
    monkeypatch.setattr(runtime.store,'put_file',lose_lease)
    assert runtime.export()
    assert claimed[0] and claimed[0]['attempts']==2
    assert staff.get(A+'/exports/'+job['id']+'/download').status_code==409
    with app.state.engine.begin() as conn:
        assert conn.execute(select(func.count()).select_from(assets).where(assets.c.kind=='export')).scalar_one()==0
        conn.execute(update(exports).where(exports.c.id==job['id']).values(lease_until='2000-01-01T00:00:00+00:00'))
    monkeypatch.setattr(runtime.store,'put_file',original)
    assert runtime.export()
    download=staff.get(A+'/exports/'+job['id']+'/download')
    assert download.status_code==200
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(assets).where(assets.c.kind=='export')).scalar_one()==1

def test_actual_killed_renderer_child_releases_slot_and_retries_same_request(system,monkeypatch):
    import subprocess,threading
    from app.self_certificates_db import jobs
    from app.application.self_certificate_slots import active_slots
    app,clients=system;staff=clients();link,_=new_link(staff)
    browser,token,prepared=prepare(app,link);assert submit(browser,token,prepared).status_code==202
    runtime=app.state.self_certificate_runtime
    killed=[]
    real_run=subprocess.run
    def kill_child(args,**kwargs):
        data=kwargs.pop('input')
        kwargs.pop('check',None)
        timeout=kwargs.pop('timeout')
        child=subprocess.Popen(args,stdin=subprocess.PIPE,**kwargs)
        timer=threading.Timer(.05,child.kill);timer.start()
        try:child.communicate(input=data,timeout=timeout)
        finally:timer.cancel()
        killed.append(child.returncode)
        return subprocess.CompletedProcess(args,child.returncode)
    with monkeypatch.context() as scoped:
        scoped.setenv('PX_SELF_CERTIFICATE_RENDER_EXECUTOR','subprocess')
        scoped.setattr(subprocess,'run',kill_child)
        assert runtime.generate()
    assert len(killed)==1 and killed[0]<0
    assert active_slots(runtime.store.root)==0
    with app.state.engine.begin() as conn:
        assert conn.execute(select(requests.c.status)).scalar_one()=='registered'
        assert conn.execute(select(func.count()).select_from(certificates)).scalar_one()==0
        conn.execute(update(jobs).values(available_at='2000-01-01T00:00:00+00:00'))
    assert runtime.generate()
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(certificates)).scalar_one()==1
        assert conn.execute(select(jobs.c.status)).scalar_one()=='done'


def test_legacy_worker_cutoff_update_is_fenced_before_claim(system):
    app,clients=system;staff=clients();link,_=new_link(staff)
    browser,token,prepared=prepare(app,link);assert submit(browser,token,prepared).status_code==202
    job=staff.post(A+'/exports',json={'format':'csv'}).json()
    # This is the exact incompatible write made by the pre-V3 claim path.
    with pytest.raises(DBAPIError):
        with app.state.engine.begin() as conn:
            conn.execute(update(exports).where(exports.c.id==job['id']).values(status='processing',
                lease_owner='old-worker',attempts=1,cutoff='2099-01-01T00:00:00+00:00'))
    with app.state.engine.connect() as conn:
        row=conn.execute(select(exports).where(exports.c.id==job['id'])).mappings().one()
        assert row['status']=='pending' and row['attempts']==0 and row['cutoff']==job['cutoff']
    assert app.state.self_certificate_runtime.export()

def test_missing_new_resource_rejects_new_but_preserves_existing_request(system,tmp_path,monkeypatch):
    app,clients=system;staff=clients();link,_=new_link(staff)
    old,token,p=prepare(app,link);assert submit(old,token,p).status_code==202
    assert app.state.self_certificate_runtime.generate()
    fresh,t,p2=prepare(app,link)
    monkeypatch.setattr(brand,'LOGO_PATH',tmp_path/'missing.png')
    app.state.self_certificate_runtime.readiness(force=True)
    assert submit(fresh,t,p2).status_code==503
    assert submit(old,token,p).json()['status']=='issued'
    with app.state.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(requests)).scalar_one()==1

def test_postgres_lease_uses_database_clock_when_application_clock_is_wrong(system,monkeypatch):
    app,clients=system
    if app.state.engine.dialect.name!='postgresql':pytest.skip('Native database clock acceptance')
    staff=clients();link,_=new_link(staff);browser,token,p=prepare(app,link)
    assert submit(browser,token,p).status_code==202
    monkeypatch.setattr(worker,'utc_now',lambda:'1900-01-01T00:00:00+00:00')
    claimed=worker.claim(app.state.engine)
    with app.state.engine.begin() as conn:
        assert worker.live_lease(conn,claimed)
    from app.application.self_certificate_clock import lease_now
    with app.state.engine.connect() as conn:
        value=datetime.fromisoformat(lease_now(conn))
    assert abs((value-datetime.now(timezone.utc)).total_seconds())<5

@pytest.mark.skipif(os.environ.get('RUN_CERTIFICATE_LARGE_IMAGES')!='YES',reason='Explicit bounded 18MP memory acceptance')
def test_six_concurrent_eighteen_megapixel_outputs_preserve_dimensions(tmp_path):
    store=CertificateStore(tmp_path/'private')
    output=BytesIO();Image.new('RGB',(6000,3000),'white').save(output,format='PNG')
    raw=output.getvalue()
    background={**store.put(raw),'id':'large-bg','owner_account_id':'synthetic-owner','kind':'background'}
    revision=dict(schema_version=2,renderer_version=renderer.VERSION,config=renderer.default_config(6000,3000),
        font_manifest=fonts.manifest('NotoSansArabic-Regular'),branding_manifest=brand.system_profile(6000,3000))
    stop=threading.Event();peak=[0];page_size=os.sysconf('SC_PAGE_SIZE')
    def sample():
        while not stop.wait(.05):
            total=0
            # This dedicated QA container contains only this test and its
            # rendering descendants. Read Linux RSS without a new dependency.
            for entry in Path('/proc').iterdir():
                if not entry.name.isdigit():continue
                try:total+=int((entry/'statm').read_text().split()[1])*page_size
                except (OSError,ValueError,IndexError):pass
            peak[0]=max(peak[0],total)
    monitor=threading.Thread(target=sample,daemon=True);monitor.start()
    started=time.perf_counter()
    try:
        def render(index):
            layout=renderer.fit_name('مشارك '+str(index),revision['config'],revision['font_manifest'],revision['branding_manifest'])
            data=worker.render_isolated(store,revision,background,None,layout)
            with Image.open(BytesIO(data)) as im:assert im.size==(6000,3000)
            return len(data)
        with ThreadPoolExecutor(max_workers=6) as pool:sizes=list(pool.map(render,range(6)))
        report={'status':'passed','pixels':18_000_000,'workers':6,'outputs':len(sizes),'output_bytes':sizes,
            'sampled_container_process_rss_peak_bytes':peak[0],'elapsed_seconds':time.perf_counter()-started,
            'limits':'Separate safety workload; does not redefine the 1000-request performance sample'}
        assert peak[0]<4*1024**3,report
        from tests.certificate_test_support import evidence_root
        (evidence_root(tmp_path)/'large-image-safety.json').write_text(json.dumps(report,indent=2))
    finally:stop.set();monitor.join()
