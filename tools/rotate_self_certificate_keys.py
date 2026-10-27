"""Explicit offline rotation retaining every previous version; never prints key bytes."""
import argparse,base64,json,os,secrets
from pathlib import Path
from app.application.self_certificate_crypto import Keyring,PART
from app.application.self_certificate_keys import atomic_private
from app.application.self_certificate_slots import try_lock

def rotate(path,version):
    path=Path(path)
    if not isinstance(version,str) or not PART.fullmatch(version):raise ValueError('KEY_VERSION_INVALID')
    lock=try_lock(path.with_name(path.name+'.rotation.lock'))
    if lock is None:raise RuntimeError('KEY_ROTATION_BUSY')
    try:
        old=Keyring(path)
        if version in old.keys:raise ValueError('KEY_VERSION_ALREADY_EXISTS')
        archive=Path(str(path)+'.versions')
        if archive.is_symlink():raise ValueError('KEY_DIRECTORY_SYMLINK_FORBIDDEN')
        versions=list(old.keys)
        for ident in versions:
            encoded=base64.urlsafe_b64encode(old.keys[ident]).decode()
            atomic_private(archive/(ident+'.json'),json.dumps({'key':encoded},sort_keys=True,separators=(',',':')).encode(),exclusive=True)
        current=base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        atomic_private(archive/(version+'.json'),json.dumps({'key':current},sort_keys=True,separators=(',',':')).encode(),exclusive=True)
        atomic_private(path,json.dumps({'current':version,'keys':{version:current}},sort_keys=True,separators=(',',':')).encode())
        return {'status':'rotated','current_version':version,'retained_versions':len(versions)+1,'previous_versions_deleted':0}
    finally:os.close(lock)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--path',type=Path,required=True)
    parser.add_argument('--version',required=True)
    args=parser.parse_args()
    print(json.dumps(rotate(args.path,args.version)))
if __name__=='__main__':main()
