"""Private upload pipeline, callable without an event; HTTP adapter is a later phase."""
from hashlib import sha256
import json
import subprocess,tempfile
import sys
from sqlalchemy import insert
from app.application.audit_service import new_id
from app.application.self_certificate_access import require_library
from app.application.self_certificate_clock import utc_now
from app.self_certificates_db import assets
from app.domain import fail
from app.application.self_certificate_sandbox import clean_environment

MAX_BACKGROUND_BYTES=3_000_000
MAX_STAMP_BYTES=999_999
MAX_NORMALIZED_BYTES=80_000_000

def validate_upload(data,kind):
    if kind not in ('background','stamp'):
        fail('ASSET_KIND_INVALID')
    if not isinstance(data,bytes) or not data:
        fail('FILE_EMPTY')
    if len(data)>(MAX_STAMP_BYTES if kind=='stamp' else MAX_BACKGROUND_BYTES):
        fail('STAMP_TOO_LARGE' if kind=='stamp' else 'BACKGROUND_TOO_LARGE')
    try:
        with tempfile.TemporaryFile() as channel:
            result=subprocess.run([sys.executable,'-m','app.application.self_certificate_asset_worker',kind],
                input=data,stdout=channel,stderr=subprocess.DEVNULL,timeout=20,check=False,env=clean_environment())
            if channel.tell()>MAX_NORMALIZED_BYTES+20_000:fail('ASSET_RESOURCE_LIMIT')
            channel.seek(0);result.stdout=channel.read(MAX_NORMALIZED_BYTES+20_001)
    except subprocess.TimeoutExpired:
        fail('ASSET_PROCESS_TIMEOUT')
    except OSError:
        fail('ASSET_PROCESS_UNAVAILABLE',503)
    if result.returncode!=0:
        fail('ASSET_RESOURCE_LIMIT')
    try:
        header,normalized=result.stdout.split(b'\n',1)
        info=json.loads(header)
    except (ValueError,UnicodeDecodeError):
        fail('ASSET_PROCESS_FAILED',503)
    if 'error' in info:
        fail(info['error'],503 if info['error']=='ASSET_PROCESS_ISOLATION_UNAVAILABLE' else 422)
    if not normalized or len(normalized)>MAX_NORMALIZED_BYTES:
        fail('ASSET_RESOURCE_LIMIT')
    return normalized,info

def ingest_asset(conn,user,store,data,kind):
    principal=require_library(conn,user)
    normalized,info=validate_upload(data,kind)
    stored=store.put(normalized)
    row=dict(id=new_id(),owner_account_id=principal['id'],kind=kind,
        storage_key=stored['storage_key'],sha256=stored['sha256'],size_bytes=stored['size_bytes'],
        mime=info['mime'],width=info['width'],height=info['height'],source_kind=info['source_kind'],
        original_size_bytes=len(data),source_metadata={**info['source_metadata'],
            'uploaded_sha256':sha256(data).hexdigest()},created_at=utc_now())
    # An aborted transaction leaves a private orphan, removed by the age-delayed bounded cleaner.
    conn.execute(insert(assets).values(**row))
    return row
