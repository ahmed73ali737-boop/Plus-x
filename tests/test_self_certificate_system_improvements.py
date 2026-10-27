"""V3 system guarantees: real confinement, process sharing, retained versions and pilot."""
from pathlib import Path
from io import BytesIO
from copy import deepcopy
from types import SimpleNamespace
import base64,json,os,secrets,subprocess,sys,time,shutil
import pytest
from fastapi import HTTPException
from sqlalchemy import select,insert,update,func
from PIL import Image
from tests.test_self_certificate_http import system,A,P,new_link,new_model,prepare,submit
from app.application.self_certificate_crypto import Keyring
from app.application.self_certificate_sandbox import clean_environment
from app.application.self_certificate_slots import render_slot
from app.application.self_certificate_runtime import CertificateWorkers
from app.application import self_certificate_rendering as renderer,self_certificate_branding as brand,self_certificate_fonts as fonts
from app.self_certificates_db import revisions,links,requests,exports,certificates,assets


def test_more_than_sixteen_key_versions_survive_restart_and_old_capability(tmp_path):
    from tools.rotate_self_certificate_keys import rotate
    path=tmp_path/'keys.json'
    old=Keyring(path,allow_create=True)
    token=old.token('receive','synthetic-cert')
    for number in range(2,22):
        result=rotate(path,'v'+str(number))
        assert result['previous_versions_deleted']==0
    current=Keyring(path)
    assert len(current.keys)==21 and current.current=='v21'
    assert current.verify('receive',token)==('synthetic-cert','v1')
    assert current.token('receive','synthetic-cert','v1')==token
    raw=json.loads(path.read_text())
    assert set(raw['keys'])=={'v21'}
    archive=Path(str(path)+'.versions')
    assert len(list(archive.glob('*.json')))==21
    if os.name=='posix':
        assert all(p.stat().st_mode&0o077==0 for p in archive.glob('*.json'))
    before=path.read_bytes()
    with pytest.raises(ValueError):rotate(path,'v1')
    assert path.read_bytes()==before
    (archive/'v1.json').unlink()
    with pytest.raises(HTTPException) as error:Keyring(path).verify('receive',token)
    assert error.value.status_code==503


def test_kernel_confinement_denies_network_exec_private_read_and_write(tmp_path):
    from tests.certificate_test_support import require_isolated_runtime
    require_isolated_runtime()
    private=tmp_path/'private.txt';private.write_text('synthetic secret')
    code="""import json,os,socket,subprocess,sys
from pathlib import Path
from app.application.self_certificate_sandbox import confine
path=Path(sys.argv[1])
confine()
results={}
for name,operation in (
 ('private_read',lambda:path.read_bytes()),
 ('arbitrary_write',lambda:path.with_name('escape.txt').write_bytes(b'x')),
 ('network',lambda:socket.socket()),
 ('exec',lambda:subprocess.run(['/bin/true'],check=True))):
 try:operation();results[name]='allowed'
 except OSError:results[name]='denied'
print(json.dumps(results))
"""
    result=subprocess.run([sys.executable,'-c',code,str(private)],env=clean_environment(),capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr.decode()
    assert set(json.loads(result.stdout).values())=={'denied'}
    assert private.read_text()=='synthetic secret' and not private.with_name('escape.txt').exists()


def _slot_child(root,active,peak,lock,iterations):
    import time
    from concurrent.futures import ThreadPoolExecutor
    from app.application.self_certificate_slots import render_slot
    def one(_):
        with render_slot(root,limit=6,timeout=15):
            with lock:
                active.value+=1;peak.value=max(peak.value,active.value)
            time.sleep(.05)
            with lock:active.value-=1
    with ThreadPoolExecutor(max_workers=6) as pool:list(pool.map(one,range(iterations)))


def test_render_slots_are_global_across_two_independent_processes(tmp_path):
    import multiprocessing as mp
    ctx=mp.get_context('spawn')
    active=ctx.Value('i',0);peak=ctx.Value('i',0);lock=ctx.Lock()
    children=[ctx.Process(target=_slot_child,args=(str(tmp_path),active,peak,lock,18)) for _ in range(2)]
    try:
        for child in children:child.start()
        for child in children:child.join(25)
        assert all(p.exitcode==0 for p in children)
        assert 1<=peak.value<=6 and active.value==0
    finally:
        for child in children:
            if child.is_alive():child.terminate();child.join()


def _service_child(root,ready,stop,pipe):
    import time,os,threading
    from pathlib import Path
    from types import SimpleNamespace
    from app.application.self_certificate_runtime import CertificateWorkers
    def generation():
        time.sleep(.02);return True
    runtime=SimpleNamespace(store=SimpleNamespace(root=Path(root)),generate=generation,export=lambda:False,
        expire_exports=lambda:None,cleanup_assets=lambda:None)
    service=CertificateWorkers(None,runtime,lambda:None,6)
    service.start()
    try:
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if service.ready():
                pipe.send({'leader':service.leader is not None,'threads':len(service.generators),'pid':os.getpid()})
                break
            time.sleep(.02)
        else:pipe.send({'error':'not_ready'})
        while not stop.wait(.05):pass
    finally:service.close();pipe.close()


def test_two_web_processes_elect_one_group_of_six_workers(tmp_path):
    import multiprocessing as mp
    ctx=mp.get_context('spawn');stop=ctx.Event();ready=ctx.Event()
    pairs=[ctx.Pipe(False) for _ in range(2)]
    children=[ctx.Process(target=_service_child,args=(str(tmp_path),ready,stop,pair[1])) for pair in pairs]
    try:
        for p in children:p.start()
        reports=[]
        for parent,_ in pairs:
            assert parent.poll(15)
            reports.append(parent.recv())
        assert sum(bool(r.get('leader')) for r in reports)==1,reports
        assert sum(r.get('threads',0) for r in reports)==6,reports
    finally:
        stop.set()
        for p in children:
            p.join(10)
            if p.is_alive():p.terminate();p.join()


def test_old_renderer_and_profile_keep_exact_pixels_after_new_revision(system):
    app,clients=system;staff=clients();model=new_model(staff)
    with app.state.engine.begin() as conn:
        old=deepcopy(model['revision']);old['id']='historical-v2';old['origin_model_id']=None
        old['renderer_version']='self-png-portable-v2'
        old['branding_manifest']=brand.system_profile(1200,800,profile_id='rts-bottom-left-14-v1')
        conn.execute(insert(revisions).values(**old))
        # An old pinned link is represented by an immutable historical witness.
        from app.application.self_certificate_links import revision_hash
    link,_=new_link(staff,model)
    with app.state.engine.begin() as conn:
        source=dict(conn.execute(select(links).where(links.c.id==link['id'])).mappings().one())
        source.update(id='historical-link',revision_id=old['id'],config_hash=revision_hash(old),
            public_id='historical-public',idempotency_key='historical-link',public_token_hash='0'*64)
        token=app.state.self_certificate_runtime.keys().token('request-link','historical-public')
        from app.application.self_certificate_crypto import token_hash
        source['public_token_hash']=token_hash(token)
        conn.execute(insert(links).values(**source))
    public={**link,'request_url':'http://testserver/certificates/request/'+token}
    browser,token,prepared=prepare(app,public)
    assert submit(browser,token,prepared).status_code==202
    assert app.state.self_certificate_runtime.generate()
    received=browser.get(P+'/request/'+token+'/mine').json()['receive_url'].split('/')[-1]
    certificate=browser.get(P+'/receive/'+received).json()
    before=browser.get(certificate['download_url']).content
    # Byte equality against an explicitly frozen v2 layout and original assets.
    with app.state.engine.connect() as conn:
        request=conn.execute(select(requests).where(requests.c.link_id=='historical-link')).mappings().one()
        background=conn.execute(select(assets).where(assets.c.id==old['background_asset_id'])).mappings().one()
    assert request['layout']['renderer_version']=='self-png-portable-v2'
    expected=renderer.render(old,app.state.self_certificate_runtime.store.read(background),None,request['layout'])
    assert expected==before
    assert model['revision']['branding_manifest']['profile_id']=='rts-bottom-left-14-v2'
    assert browser.get(certificate['download_url']).content==before


def test_historical_font_catalog_resolves_after_current_catalog_changes(tmp_path,monkeypatch):
    saved=fonts.manifest('NotoSansArabic-Regular')
    row=dict(schema_version=2,renderer_version=renderer.VERSION,config=renderer.default_config(1200,800),
        font_manifest=saved,branding_manifest=brand.system_profile(1200,800))
    image=BytesIO();Image.new('RGB',(1200,800),'white').save(image,format='PNG')
    before,layout=renderer.preview(row,image.getvalue(),None,'محمد أحمد العمري')
    target=tmp_path/'fonts';shutil.copytree(fonts.ROOT,target)
    rows=json.loads((target/'noto-manifest.json').read_bytes())
    alternate=next(r for r in rows if r['id']=='NotoNaskhArabic-Regular')['sha256']
    next(r for r in rows if r['id']=='NotoSansArabic-Regular')['sha256']=alternate
    raw=json.dumps(rows,ensure_ascii=False).encode()
    (target/'noto-manifest.json').write_bytes(raw)
    from hashlib import sha256
    monkeypatch.setattr(fonts,'ROOT',target);monkeypatch.setattr(fonts,'MANIFEST_HASH',sha256(raw).hexdigest())
    assert fonts.manifest('NotoSansArabic-Regular')!=saved
    assert fonts.validate_manifest(saved)==saved
    assert renderer.render(row,image.getvalue(),None,layout)==before
    (target/(saved['primary_sha256']+'.ttf')).unlink()
    with pytest.raises(HTTPException):fonts.validate_manifest(saved)


def test_pilot_scope_limits_new_but_keeps_previous_delivery(system,monkeypatch):
    app,clients=system;staff=clients();model=new_model(staff);link,_=new_link(staff,model)
    browser,token,prepared=prepare(app,link)
    assert submit(browser,token,prepared).status_code==202
    assert app.state.self_certificate_runtime.generate()
    received=browser.get(P+'/request/'+token+'/mine').json()['receive_url'].split('/')[-1]
    before=browser.get(P+'/receive/'+received).json()
    monkeypatch.setenv('PX_SELF_CERTIFICATE_PILOT_ACCOUNTS','self-b')
    assert not staff.get(A+'/access').json()['can_manage']
    assert staff.get(A+'/models').status_code==409
    fresh,t,data=prepare(app,link)
    assert submit(fresh,t,data).status_code==409
    assert submit(browser,token,prepared).json()['status']=='issued'
    assert browser.get(before['download_url']).status_code==200
    assert staff.get(A+'/requests').status_code==200
    monkeypatch.setenv('PX_SELF_CERTIFICATE_PILOT_ACCOUNTS','self-a')
    monkeypatch.setenv('PX_SELF_CERTIFICATE_PILOT_EVENTS','another-event')
    assert staff.get(A+'/access').json()['can_manage']
    assert staff.get(A+'/access').json()['events']==[]
    fresh,t,data=prepare(app,link)
    assert submit(fresh,t,data).status_code==409

def test_installed_runtime_outside_usr_is_readable_but_private_sibling_is_not(tmp_path):
    from tests.certificate_test_support import require_isolated_runtime
    require_isolated_runtime()
    runtime=tmp_path/'runtime/site-packages';runtime.mkdir(parents=True)
    marker=runtime/'package.dat';marker.write_bytes(b'public-installed-library')
    private=tmp_path/'private.dat';private.write_bytes(b'synthetic-private')
    code="""import json,sys,sysconfig
from pathlib import Path
from app.application.self_certificate_sandbox import confine
runtime=Path(sys.argv[1]);private=Path(sys.argv[2])
original=sysconfig.get_path
sysconfig.get_path=lambda name,*a,**kw:str(runtime) if name in ('purelib','platlib') else original(name,*a,**kw)
confine()
result={'runtime_read':(runtime/'package.dat').read_bytes()==b'public-installed-library'}
try:private.read_bytes();result['private_denied']=False
except PermissionError:result['private_denied']=True
print(json.dumps(result))
"""
    result=subprocess.run([sys.executable,'-c',code,str(runtime),str(private)],
        env=clean_environment(),capture_output=True,timeout=10)
    assert result.returncode==0,result.stderr.decode()
    assert json.loads(result.stdout)=={'runtime_read':True,'private_denied':True}


def test_unavailable_confinement_never_runs_unconfined(monkeypatch):
    from app.application import self_certificate_sandbox as sandbox
    monkeypatch.setattr(sandbox,'availability',lambda:False)
    with pytest.raises(sandbox.IsolationUnavailable):
        sandbox.confine()
