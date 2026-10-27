"""Leased queue with fencing, file-before-issued and bounded rendering."""
from datetime import datetime,timedelta,timezone
from io import BytesIO
import json,secrets,subprocess,sys,threading,tempfile
import os
from fastapi import HTTPException
from PIL import Image
from sqlalchemy import select,update,insert,or_,and_
from sqlalchemy.exc import DBAPIError
from app.self_certificates_db import jobs,requests,certificates,assets,links
from app.application.self_certificate_clock import utc_now,lease_now
from app.application.audit_service import new_id
from app.application.self_certificate_links import checked_revision,revision_hash
from app.application.self_certificate_delivery import certificate_integrity
from app.application.self_certificate_crypto import token_hash
from app.domain import fail
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
        fail('CERTIFICATE_RENDER_BUSY',429)
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
                        if result.returncode:fail('CERTIFICATE_RENDER_UNAVAILABLE',503)
                        if channel.tell()>80_020_000:fail('CERTIFICATE_RENDER_UNAVAILABLE',503)
                        channel.seek(0);output=channel.read(80_020_001)
                else:fail('CERTIFICATE_RENDER_EXECUTOR_INVALID',503)
        except (OSError,subprocess.TimeoutExpired):fail('CERTIFICATE_RENDER_UNAVAILABLE',503)
        try:
            header,image=output.split(b'\n',1)
            report=json.loads(header)
            if report.get('error') or not image or len(image)>80_000_000:raise ValueError()
            if isinstance(report.get('render_seconds'),(int,float)):
                record('render_child',seconds=max(0,report['render_seconds']))
        except (ValueError,UnicodeDecodeError):fail('CERTIFICATE_RENDER_UNAVAILABLE',503)
        return image
    finally:_RENDER.release()

@timed('lease')
def claim(engine,lease_seconds=60):
    with engine.begin() as conn:
        at=lease_now(conn)
        exhausted=conn.execute(select(jobs.c.id,jobs.c.request_id).where(jobs.c.attempts>=3,or_(
            and_(jobs.c.status.in_(('pending','retry_wait')),jobs.c.available_at<=at),
            and_(jobs.c.status=='leased',jobs.c.lease_until<at))).order_by(jobs.c.available_at,jobs.c.id)
            .limit(100).with_for_update(skip_locked=True)).all()
        for item in exhausted:
            conn.execute(update(jobs).where(jobs.c.id==item.id).values(status='failed',lease_owner=None,lease_until=None,last_error_code='GENERATION_FAILED'))
            conn.execute(update(requests).where(requests.c.id==item.request_id,requests.c.status!='issued')
                .values(status='failed',error_code='GENERATION_FAILED'))
        row=conn.execute(select(jobs).where(or_(
            and_(jobs.c.status.in_(('pending','retry_wait')),jobs.c.available_at<=at),
            and_(jobs.c.status=='leased',jobs.c.lease_until<at)),jobs.c.attempts<3)
            .order_by(jobs.c.available_at,jobs.c.id).limit(1).with_for_update(skip_locked=True)).mappings().first()
        if not row:return None
        token=new_id();row=dict(row)
        # Compare-and-swap also protects SQLite's non-locking SELECT.
        condition=and_(jobs.c.id==row['id'],jobs.c.status==row['status'],jobs.c.attempts==row['attempts'])
        changed=conn.execute(update(jobs).where(condition).values(status='leased',attempts=row['attempts']+1,
            lease_owner=token,lease_until=later(lease_seconds,at)))
        if changed.rowcount!=1:return None
        if conn.execute(select(certificates.c.id).where(certificates.c.request_id==row['request_id'])).first():
            conn.execute(update(jobs).where(jobs.c.id==row['id']).values(status='done',lease_owner=None,lease_until=None))
            conn.execute(update(requests).where(requests.c.id==row['request_id']).values(status='issued',error_code=None))
            return None
        conn.execute(update(requests).where(requests.c.id==row['request_id']).values(status='processing',error_code=None))
        return {**row,'lease_owner':token,'attempts':row['attempts']+1}

def live_lease(conn,job):
    return conn.execute(select(jobs).where(jobs.c.id==job['id'],jobs.c.status=='leased',
        jobs.c.lease_owner==job['lease_owner'],jobs.c.lease_until>lease_now(conn)).with_for_update()).mappings().first()

def generation_inputs(conn,job):
    row=conn.execute(select(requests).where(requests.c.id==job['request_id'])).mappings().one()
    link=conn.execute(select(links).where(links.c.id==row['link_id'],links.c.owner_account_id==row['owner_account_id'],
        links.c.revision_id==row['revision_id'])).mappings().first()
    if not link:fail('REQUEST_OWNER_CHAIN_INVALID',409)
    revision=checked_revision(conn,row['owner_account_id'],row['revision_id'])
    if revision_hash(revision)!=link['config_hash']:fail('REVISION_INTEGRITY_ERROR',409)
    background=dict(conn.execute(select(assets).where(assets.c.id==revision['background_asset_id'])).mappings().one())
    stamp=dict(conn.execute(select(assets).where(assets.c.id==revision['stamp_asset_id'])).mappings().one()) if revision['stamp_asset_id'] else None
    return dict(row),revision,background,stamp

def asset_row(owner,kind,stored,width,height,renderer_version):
    return dict(id=new_id(),owner_account_id=owner,kind=kind,**stored,mime='image/png',
        width=width,height=height,source_kind='render',original_size_bytes=stored['size_bytes'],
        source_metadata={'renderer':renderer_version},created_at=utc_now())

def fail_job(engine,job,error):
    temporary=isinstance(error,(OSError,DBAPIError)) or isinstance(error,HTTPException) and error.status_code in (429,503)
    busy=isinstance(error,HTTPException) and error.detail=='CERTIFICATE_RENDER_BUSY'
    retry=temporary and (busy or job['attempts']<3)
    record('retry' if retry else 'failed')
    with engine.begin() as conn:
        if not live_lease(conn,job):return
        code='GENERATION_RETRY' if retry else 'GENERATION_FAILED'
        conn.execute(update(jobs).where(jobs.c.id==job['id']).values(status='retry_wait' if retry else 'failed',
            available_at=later(1 if busy else 5*job['attempts'],lease_now(conn)),attempts=job['attempts']-1 if busy else job['attempts'],
            lease_owner=None,lease_until=None,last_error_code=code))
        conn.execute(update(requests).where(requests.c.id==job['request_id']).values(status='registered' if retry else 'failed',error_code=code))

@timed('generation')
def process_one(engine,store,key_factory,job=None):
    job=job or claim(engine)
    if not job:return False
    try:
        keys=key_factory()
        with engine.connect() as conn:
            request,revision,background,stamp=generation_inputs(conn,job)
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
        with engine.begin() as conn:
            if not live_lease(conn,job):return True
            if conn.execute(select(certificates.c.id).where(certificates.c.request_id==request['id'])).first():return True
            ident=new_id();token=keys.token('receive',ident)
            issued=dict(id=ident,owner_account_id=request['owner_account_id'],request_id=request['id'],link_id=request['link_id'],
                serial='SC'+secrets.token_hex(16).upper(),name_printed=request['layout']['name_printed'],
                layout=request['layout'],issued_at_utc=utc_now(),final_asset_id=final['id'],thumbnail_asset_id=thumbnail['id'],
                delivery_token_hash=token_hash(token),key_version=keys.current,source='self_service',schema_version=2)
            issued['integrity_hash']=certificate_integrity(issued,final,thumbnail)
            conn.execute(insert(assets),[final,thumbnail])
            conn.execute(insert(certificates).values(**issued))
            conn.execute(update(requests).where(requests.c.id==request['id']).values(status='issued',error_code=None))
            conn.execute(update(jobs).where(jobs.c.id==job['id']).values(status='done',lease_owner=None,lease_until=None,last_error_code=None))
        record('issued')
        return True
    except Exception as error:
        fail_job(engine,job,error)
        return True
