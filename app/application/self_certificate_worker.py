"""Leased queue with fencing, file-before-issued and bounded rendering."""
from datetime import datetime,timedelta,timezone
from io import BytesIO
import json,secrets,subprocess,sys,threading,tempfile
import os
from PIL import Image
from app.application.ports import persistence
from app.application.self_certificate_clock import utc_now,lease_now
from app.application.audit_service import new_id
from app.application.self_certificate_links import checked_revision,revision_hash
from app.application.self_certificate_delivery import certificate_integrity
from app.application.self_certificate_crypto import token_hash
from app.domain import fail, Conflict, RateLimited, Unavailable, DomainError
from app.application.self_certificate_metrics import timed,record
from app.application.self_certificate_slots import render_slot
from app.application.self_certificate_sandbox import clean_environment

try:
    _RENDER_CONCURRENCY=int(os.environ.get('PX_SELF_CERTIFICATE_RENDER_CONCURRENCY','6'))
except ValueError as error:
    raise RuntimeError('INVALID_SELF_CERTIFICATE_RENDER_CONCURRENCY') from error
if not 1<=_RENDER_CONCURRENCY<=6:
    raise RuntimeError('INVALID_SELF_CERTIFICATE_RENDER_CONCURRENCY')
_RENDER=threading.BoundedSemaphore(_RENDER_CONCURRENCY)
def later(seconds,at=None):
    return ((datetime.fromisoformat(at) if at else datetime.now(timezone.utc))+timedelta(seconds=seconds)).isoformat(timespec='microseconds')

@timed('render')
def render_isolated(store,revision,background,stamp,layout):
    if not _RENDER.acquire(timeout=5):
        record('render_busy')
        fail('CERTIFICATE_RENDER_BUSY', RateLimited)
    try:
        payload=dict(root=str(store.root),revision=revision,background=background,stamp=stamp,layout=layout)
        try:
            with render_slot(store.root,_RENDER_CONCURRENCY):
                mode=os.environ.get('PX_SELF_CERTIFICATE_RENDER_EXECUTOR','supervisor')
                if mode=='supervisor':
                    from app.application.self_certificate_executor import execute
                    output=execute(payload)
                elif mode=='subprocess':
                    with tempfile.TemporaryFile() as channel:
                        result=subprocess.run([sys.executable,'-m','app.application.self_certificate_render_worker'],
                            input=json.dumps(payload,ensure_ascii=False).encode(),stdout=channel,stderr=subprocess.DEVNULL,
                            timeout=30,check=False,env=clean_environment())
                        if result.returncode:fail('CERTIFICATE_RENDER_UNAVAILABLE', Unavailable)
                        if channel.tell()>80_020_000:fail('CERTIFICATE_RENDER_UNAVAILABLE', Unavailable)
                        channel.seek(0);output=channel.read(80_020_001)
                else:fail('CERTIFICATE_RENDER_EXECUTOR_INVALID', Unavailable)
        except (OSError,subprocess.TimeoutExpired):fail('CERTIFICATE_RENDER_UNAVAILABLE', Unavailable)
        try:
            header,image=output.split(b'\n',1)
            report=json.loads(header)
            if report.get('error') or not image or len(image)>80_000_000:raise ValueError()
            if isinstance(report.get('render_seconds'),(int,float)):
                record('render_child',seconds=max(0,report['render_seconds']))
        except (ValueError,UnicodeDecodeError):fail('CERTIFICATE_RENDER_UNAVAILABLE', Unavailable)
        return image
    finally:_RENDER.release()

@timed('lease')
def claim(engine,lease_seconds=60):
    store=persistence.self_certificates
    with persistence.transactions.write(engine) as tx:
        at=lease_now(tx)
        store.fail_exhausted_jobs(tx,at)
        row=store.next_job(tx,at)
        if not row:return None
        token=new_id()
        if not store.lease_job(tx,row,token,later(lease_seconds,at)):return None
        if store.certificate_exists_for_request(tx,row['request_id']):
            store.finish_job(tx,row['id'],dict(status='done',lease_owner=None,lease_until=None))
            store.set_request_state(tx,row['request_id'],'issued',None)
            return None
        store.set_request_state(tx,row['request_id'],'processing',None)
        return {**row,'lease_owner':token,'attempts':row['attempts']+1}

def live_lease(tx,job):
    return persistence.self_certificates.live_lease(tx,job,lease_now(tx))

def generation_inputs(tx,job):
    store=persistence.self_certificates
    row=store.request(tx,job['request_id'])
    link=store.link_of(tx,row['link_id'],row['owner_account_id'],row['revision_id'])
    if not link:fail('REQUEST_OWNER_CHAIN_INVALID', Conflict)
    revision=checked_revision(tx,row['owner_account_id'],row['revision_id'])
    if revision_hash(revision)!=link['config_hash']:fail('REVISION_INTEGRITY_ERROR', Conflict)
    background=store.asset_by_id(tx,revision['background_asset_id'])
    stamp=store.asset_by_id(tx,revision['stamp_asset_id']) if revision['stamp_asset_id'] else None
    return row,revision,background,stamp

def asset_row(owner,kind,stored,width,height,renderer_version):
    return dict(id=new_id(),owner_account_id=owner,kind=kind,**stored,mime='image/png',
        width=width,height=height,source_kind='render',original_size_bytes=stored['size_bytes'],
        source_metadata={'renderer':renderer_version},created_at=utc_now())

def fail_job(engine,job,error):
    temporary=isinstance(error,OSError) or persistence.transactions.is_transient_failure(error) or isinstance(error,(RateLimited,Unavailable))
    busy=isinstance(error,DomainError) and error.code=='CERTIFICATE_RENDER_BUSY'
    retry=temporary and (busy or job['attempts']<3)
    record('retry' if retry else 'failed')
    store=persistence.self_certificates
    with persistence.transactions.write(engine) as tx:
        if not live_lease(tx,job):return
        code='GENERATION_RETRY' if retry else 'GENERATION_FAILED'
        store.finish_job(tx,job['id'],dict(status='retry_wait' if retry else 'failed',
            available_at=later(1 if busy else 5*job['attempts'],lease_now(tx)),attempts=job['attempts']-1 if busy else job['attempts'],
            lease_owner=None,lease_until=None,last_error_code=code))
        store.set_request_state(tx,job['request_id'],'registered' if retry else 'failed',code)

@timed('generation')
def process_one(engine,store,key_factory,job=None):
    job=job or claim(engine)
    if not job:return False
    try:
        keys=key_factory()
        with persistence.transactions.read(engine) as tx:
            request,revision,background,stamp=generation_inputs(tx,job)
        image=render_isolated(store,revision,background,stamp,request['layout'])
        final_stored=store.put(image)
        with Image.open(BytesIO(image)) as original:
            width,height=original.size
            original.thumbnail((480,480),Image.Resampling.LANCZOS)
            thumb=BytesIO();original.save(thumb,format='PNG');thumb_size=original.size
        thumb_stored=store.put(thumb.getvalue())
        final=asset_row(request['owner_account_id'],'final',final_stored,width,height,revision['renderer_version'])
        thumbnail=asset_row(request['owner_account_id'],'thumbnail',thumb_stored,*thumb_size,revision['renderer_version'])
        # File integrity is checked before the database success transaction.
        store.verified_path(final);store.verified_path(thumbnail)
        store=persistence.self_certificates
        with persistence.transactions.write(engine) as tx:
            if not live_lease(tx,job):return True
            if store.certificate_exists_for_request(tx,request['id']):return True
            ident=new_id();token=keys.token('receive',ident)
            issued=dict(id=ident,owner_account_id=request['owner_account_id'],request_id=request['id'],link_id=request['link_id'],
                serial='SC'+secrets.token_hex(16).upper(),name_printed=request['layout']['name_printed'],
                layout=request['layout'],issued_at_utc=utc_now(),final_asset_id=final['id'],thumbnail_asset_id=thumbnail['id'],
                delivery_token_hash=token_hash(token),key_version=keys.current,source='self_service',schema_version=2)
            issued['integrity_hash']=certificate_integrity(issued,final,thumbnail)
            store.issue(tx,final,thumbnail,issued)
            store.set_request_state(tx,request['id'],'issued',None)
            store.finish_job(tx,job['id'],dict(status='done',lease_owner=None,lease_until=None,last_error_code=None))
        record('issued')
        return True
    except Exception as error:
        fail_job(engine,job,error)
        return True
