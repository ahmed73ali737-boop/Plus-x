"""Explicit PostgreSQL + DATA_DIR + pinned resources backup; restore only into empty targets."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,os,re,shutil,subprocess,tempfile,time,zipfile
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
NAME=re.compile(r'^[A-Za-z0-9_-]{1,100}$')
DBNAME=re.compile(r'^[A-Za-z0-9_]{1,63}$')

def command(container,user,database,program,*args):
    if not NAME.fullmatch(container) or not DBNAME.fullmatch(user) or not DBNAME.fullmatch(database):
        raise ValueError('BACKUP_TARGET_INVALID')
    return ['docker','exec','-i',container,program,'-U',user,'-d',database,*args]

def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk:=stream.read(1024*1024):h.update(chunk)
    return h.hexdigest()

def run_checked(args,**kwargs):
    result=subprocess.run(args,stderr=subprocess.PIPE,**kwargs)
    if result.returncode:raise RuntimeError('BACKUP_DATABASE_COMMAND_FAILED')
    return result

def backup(container,user,database,data_dir,destination,*,writers_stopped=False,keyring=None):
    if not writers_stopped:raise RuntimeError('STOP_ALL_WRITERS_BEFORE_CONSISTENT_BACKUP')
    started=time.monotonic();data_dir=Path(data_dir).resolve();destination=Path(destination).resolve()
    if not data_dir.is_dir() or destination.exists() or destination.is_relative_to(data_dir):
        raise ValueError('BACKUP_PATH_INVALID')
    destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    files={}
    with tempfile.TemporaryDirectory(prefix='certificate-backup-') as temp:
        dump=Path(temp)/'database.dump'
        with dump.open('xb') as stream:
            run_checked(command(container,user,database,'pg_dump','--format=custom','--no-owner','--no-acl'),stdout=stream)
        candidates=[('database.dump',dump)]
        for source,prefix in [(data_dir,'data'),(ROOT/'app/resources','resources')]:
            for path in source.rglob('*'):
                if not path.is_file() or path.is_symlink() or '.runtime' in path.relative_to(source).parts:continue
                if prefix=='data' and path.name in ('first-run-accounts.json','bootstrap-admin.json'):continue
                candidates.append((prefix+'/'+path.relative_to(source).as_posix(),path))
        # The legacy service predates app/resources and pins this shipped font.
        legacy_font=ROOT/'web/fonts/CertificateSans.ttf'
        if legacy_font.is_file():
            candidates.append(('resources/legacy/CertificateSans.ttf',legacy_font))
        keyring_in_data=None
        if keyring:
            keyring=Path(keyring).resolve()
            if keyring.is_relative_to(data_dir):keyring_in_data=keyring.relative_to(data_dir).as_posix()
            else:
                candidates.append(('keys/keyring.json',keyring))
                archive=Path(str(keyring)+'.versions')
                if archive.exists():
                    for path in archive.glob('*.json'):
                        if path.is_file() and not path.is_symlink():candidates.append(('keys/keyring.json.versions/'+path.name,path))
        fd=os.open(destination,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        try:
            with os.fdopen(fd,'wb') as stream,zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED,allowZip64=True) as archive:
                for name,path in candidates:
                    files[name]={'sha256':digest(path),'size_bytes':path.stat().st_size}
                    archive.write(path,name)
                manifest={'format_version':1,'created_at':datetime.now(timezone.utc).isoformat(),
                    'contains_sensitive_data':True,'writers_stopped_by_operator':True,'files':files,
                    'keyring_in_data':keyring_in_data,'external_keyring':bool(keyring and keyring_in_data is None),
                    'target_rpo_hours':24,'target_rto_hours':8,'kind':'logical_pg_dump_plus_immutable_files',
                    'production_schedule_accepted':False}
                archive.writestr('BACKUP-MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            # Verify the artifact before reporting a completed backup.
            verify(destination)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    return {'status':'backed_up','artifact':str(destination),'sha256':digest(destination),
        'file_count':len(files),'elapsed_seconds':time.monotonic()-started,'contains_sensitive_data':True}

def verify(source):
    with zipfile.ZipFile(source) as archive:
        manifest=json.loads(archive.read('BACKUP-MANIFEST.json'))
        if manifest.get('format_version')!=1:raise ValueError('BACKUP_FORMAT_INVALID')
        names=archive.namelist()
        if len(set(names))!=len(names) or set(names)!=set(manifest['files'])|{'BACKUP-MANIFEST.json'}:
            raise ValueError('BACKUP_MEMBERS_INVALID')
        for name,item in manifest['files'].items():
            path=PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or path.as_posix()!=name:
                raise ValueError('BACKUP_PATH_INVALID')
            if name!='database.dump' and not name.startswith(('data/','resources/','keys/')):
                raise ValueError('BACKUP_PATH_INVALID')
            info=archive.getinfo(name)
            if info.file_size!=item['size_bytes']:raise ValueError('BACKUP_SIZE_INVALID')
            h=hashlib.sha256()
            with archive.open(name) as stream:
                while chunk:=stream.read(1024*1024):h.update(chunk)
            if h.hexdigest()!=item['sha256']:raise ValueError('BACKUP_HASH_INVALID')
        return manifest

def restore(source,container,user,database,new_data_dir):
    started=time.monotonic();source=Path(source).resolve();new_data_dir=Path(new_data_dir).resolve()
    if new_data_dir.exists():raise ValueError('RESTORE_REQUIRES_NEW_DATA_DIRECTORY')
    manifest=verify(source)
    tables=run_checked(command(container,user,database,'psql','-Atqc',
        "SELECT count(*) FROM pg_tables WHERE schemaname='public'"),stdout=subprocess.PIPE).stdout.strip()
    if tables!=b'0':raise RuntimeError('RESTORE_REQUIRES_EMPTY_DATABASE')
    new_data_dir.mkdir(parents=True,mode=0o700)
    # All output resolves below the explicitly new target. No overwrite,
    # recursive deletion, down-migration, or running-service restart.
    with tempfile.TemporaryDirectory(prefix='certificate-restore-') as temp,zipfile.ZipFile(source) as archive:
        dump=Path(temp)/'database.dump'
        with archive.open('database.dump') as incoming,dump.open('xb') as outgoing:shutil.copyfileobj(incoming,outgoing)
        with dump.open('rb') as stream:
            run_checked(command(container,user,database,'pg_restore','--exit-on-error','--no-owner','--no-acl'),stdin=stream,stdout=subprocess.DEVNULL)
        for name in manifest['files']:
            if name=='database.dump':continue
            if name.startswith('data/'):relative=PurePosixPath(name).relative_to('data')
            elif name.startswith('resources/'):relative=PurePosixPath('restore-resources')/PurePosixPath(name).relative_to('resources')
            elif name.startswith('keys/'):relative=PurePosixPath('restore-keys')/PurePosixPath(name).relative_to('keys')
            else:raise ValueError('BACKUP_PATH_INVALID')
            target=new_data_dir.joinpath(*relative.parts)
            if not target.resolve().is_relative_to(new_data_dir):raise ValueError('RESTORE_PATH_INVALID')
            target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as outgoing,archive.open(name) as incoming:shutil.copyfileobj(incoming,outgoing)
            if digest(target)!=manifest['files'][name]['sha256']:raise ValueError('RESTORE_HASH_INVALID')
    return {'status':'restored','new_data_dir':str(new_data_dir),'elapsed_seconds':time.monotonic()-started,
        'target_rto_hours':8,'production_RTO_accepted':False,'source_created_at':manifest['created_at']}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['backup','verify','restore','check-age'])
    parser.add_argument('--artifact',type=Path,required=True)
    parser.add_argument('--container');parser.add_argument('--user');parser.add_argument('--database')
    parser.add_argument('--data-dir',type=Path);parser.add_argument('--keyring',type=Path)
    parser.add_argument('--writers-stopped',action='store_true')
    args=parser.parse_args()
    if args.action=='backup':
        result=backup(args.container,args.user,args.database,args.data_dir,args.artifact,writers_stopped=args.writers_stopped,keyring=args.keyring)
    elif args.action=='restore':
        result=restore(args.artifact,args.container,args.user,args.database,args.data_dir)
    else:
        manifest=verify(args.artifact)
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(manifest['created_at'])).total_seconds()/3600
        result={'status':'verified','file_count':len(manifest['files']),'age_hours':age,'rpo_target_hours':24}
        if args.action=='check-age' and age>24:
            print(json.dumps({**result,'status':'backup_stale'}));return 2
    print(json.dumps(result));return 0
if __name__=='__main__':raise SystemExit(main())
