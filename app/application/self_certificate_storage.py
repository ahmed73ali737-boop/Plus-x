"""Private immutable assets. No static route serves this directory."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import os, re, secrets, time
from sqlalchemy import select, delete, or_, and_, exists
from app.self_certificates_db import assets, revisions, certificates, exports
from app.domain import fail
from app.application.self_certificate_metrics import timed,record

KEY = re.compile(r'^[0-9a-f]{2}/[0-9a-f]{64}$')

class CertificateStore:
    def __init__(self, root):
        self.root=Path(root).resolve()
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)

    def path(self,key):
        if not isinstance(key,str) or not KEY.fullmatch(key):
            fail('ASSET_KEY_INVALID',422)
        path=(self.root/key).resolve()
        if not path.is_relative_to(self.root):
            fail('ASSET_KEY_INVALID',422)
        return path

    @timed('storage')
    def put(self,content):
        if not isinstance(content,bytes) or not content:
            fail('EMPTY_ASSET',422)
        key=secrets.token_hex(32)
        key=key[:2]+'/'+key
        target=self.path(key)
        target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        temporary=target.with_name(target.name+'.'+secrets.token_hex(8)+'.tmp')
        try:
            with temporary.open('xb') as stream:
                os.chmod(temporary,0o600)
                stream.write(content);stream.flush();os.fsync(stream.fileno())
            # Target names are never reused by another attempt or owner.
            os.replace(temporary,target)
            if os.name!='nt':
                descriptor=os.open(str(target.parent),os.O_RDONLY)
                try:os.fsync(descriptor)
                finally:os.close(descriptor)
        except OSError:
            record('storage_error')
            if temporary.exists():temporary.unlink()
            fail('ASSET_STORAGE_UNAVAILABLE',503)
        return {'storage_key':key,'sha256':sha256(content).hexdigest(),'size_bytes':len(content)}

    @timed('storage')
    def read(self,asset):
        try:
            path=self.path(asset['storage_key'])
            if path.stat().st_size!=asset['size_bytes']:fail('FINAL_FILE_UNAVAILABLE',503)
            content=path.read_bytes()
            if sha256(content).hexdigest()!=asset['sha256']:fail('FINAL_FILE_UNAVAILABLE',503)
            return content
        except OSError:
            record('storage_error')
            fail('FINAL_FILE_UNAVAILABLE',503)

    def remove_unreferenced_file(self,key):
        target=self.path(key)
        try:target.unlink(missing_ok=True)
        except OSError:return False
        return True

    @timed('storage')
    def put_file(self,source):
        key=secrets.token_hex(32);key=key[:2]+'/'+key
        target=self.path(key);target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        temporary=target.with_name(target.name+'.'+secrets.token_hex(8)+'.tmp')
        checksum=sha256();size=0
        try:
            with Path(source).open('rb') as incoming,temporary.open('xb') as outgoing:
                os.chmod(temporary,0o600)
                while chunk:=incoming.read(1024*1024):
                    checksum.update(chunk);size+=len(chunk);outgoing.write(chunk)
                outgoing.flush();os.fsync(outgoing.fileno())
            os.replace(temporary,target)
            if os.name!='nt':
                descriptor=os.open(str(target.parent),os.O_RDONLY)
                try:os.fsync(descriptor)
                finally:os.close(descriptor)
        except OSError:
            record('storage_error')
            temporary.unlink(missing_ok=True);fail('ASSET_STORAGE_UNAVAILABLE',503)
        return dict(storage_key=key,sha256=checksum.hexdigest(),size_bytes=size)

    @timed('storage')
    def verified_path(self,asset):
        try:
            path=self.path(asset['storage_key']);stat=path.stat()
            if stat.st_size!=asset['size_bytes'] or not _verify_cached(str(path),stat.st_ino,stat.st_mtime_ns,stat.st_ctime_ns,stat.st_size,asset['sha256']):
                fail('FINAL_FILE_UNAVAILABLE',503)
            return path
        except OSError:
            record('storage_error')
            fail('FINAL_FILE_UNAVAILABLE',503)

from functools import lru_cache
@lru_cache(maxsize=1024)
def _verify_cached(path,inode,modified,changed,size,expected):
    checksum=sha256()
    with open(path,'rb') as stream:
        while chunk:=stream.read(1024*1024):checksum.update(chunk)
    return checksum.hexdigest()==expected

def asset_referenced(conn,asset_id):
    return bool(conn.execute(select(revisions.c.id).where(or_(
        revisions.c.background_asset_id==asset_id,revisions.c.stamp_asset_id==asset_id)).limit(1)).first()
        or conn.execute(select(certificates.c.id).where(or_(
        certificates.c.final_asset_id==asset_id,certificates.c.thumbnail_asset_id==asset_id)).limit(1)).first()
        or conn.execute(select(exports.c.id).where(exports.c.asset_id==asset_id).limit(1)).first())

def cleanup_unreferenced(engine,store,*,minimum_age_hours=24,batch_size=100):
    """Keep every referenced revision, including detached library revisions.

    This deliberately does not purge participants, issued records or historical
    revisions. Call from a scheduled worker; bounded batches and a grace period
    protect in-flight uploads and file/DB commit gaps.
    """
    if minimum_age_hours<24 or not 1<=batch_size<=1000:
        raise ValueError('UNSAFE_CLEANUP_CONFIGURATION')
    cutoff=(datetime.now(timezone.utc)-timedelta(hours=minimum_age_hours)).isoformat()
    result={'removed_records':0,'removed_files':0,'file_errors':0}
    keys=[]
    with engine.begin() as conn:
        unreferenced=and_(
            ~exists(select(revisions.c.id).where(or_(revisions.c.background_asset_id==assets.c.id,revisions.c.stamp_asset_id==assets.c.id))),
            ~exists(select(certificates.c.id).where(or_(certificates.c.final_asset_id==assets.c.id,certificates.c.thumbnail_asset_id==assets.c.id))),
            ~exists(select(exports.c.id).where(exports.c.asset_id==assets.c.id)))
        candidates=conn.execute(select(assets).where(assets.c.created_at<cutoff,unreferenced)
            .order_by(assets.c.created_at,assets.c.id).limit(batch_size)
            .with_for_update(skip_locked=True)).mappings()
        for row in candidates:
            if asset_referenced(conn,row['id']):continue
            conn.execute(delete(assets).where(assets.c.id==row['id']))
            keys.append(row['storage_key']);result['removed_records']+=1
    for key in keys:
        if store.remove_unreferenced_file(key):result['removed_files']+=1
        else:result['file_errors']+=1
    # Recover files left before an asset row committed. Never traverse symlinks
    # or accept filenames outside this store's opaque key grammar.
    deadline=time.time()-minimum_age_hours*3600
    inspected=0
    for folder in store.root.iterdir():
        if folder.is_symlink() or not folder.is_dir() or not re.fullmatch('[0-9a-f]{2}',folder.name):continue
        for path in folder.iterdir():
            inspected+=1
            if inspected>batch_size*10:return result
            if path.is_symlink() or not path.is_file():continue
            if re.fullmatch(r'[0-9a-f]{64}[.][0-9a-f]{16}[.]tmp',path.name) and path.stat().st_mtime<deadline:
                resolved=path.resolve()
                if not resolved.is_relative_to(store.root):continue
                try:resolved.unlink();result['removed_files']+=1
                except OSError:result['file_errors']+=1
                continue
            key=folder.name+'/'+path.name
            if not KEY.fullmatch(key) or path.stat().st_mtime>=deadline:continue
            with engine.connect() as conn:
                if conn.execute(select(assets.c.id).where(assets.c.storage_key==key).limit(1)).first():continue
            if store.remove_unreferenced_file(key):result['removed_files']+=1
            else:result['file_errors']+=1
    return result
