"""Lazy immutable version files retain old HMAC capabilities across rotations."""
import base64,json,os,secrets
from collections.abc import Mapping
from pathlib import Path

def bounded_json(path,maximum):
    path=Path(path)
    if path.is_symlink():raise ValueError('KEY_FILE_SYMLINK_FORBIDDEN')
    with path.open('rb') as stream:
        data=stream.read(maximum+1)
    if len(data)>maximum:raise ValueError('KEY_FILE_LIMIT')
    return json.loads(data)

def decoded(value):
    raw=base64.b64decode(value,altchars=b'-_',validate=True)
    if not 32<=len(raw)<=128:raise ValueError('KEY_LENGTH_INVALID')
    return raw

class VersionedKeys(Mapping):
    def __init__(self,path,embedded,pattern):
        self.directory=Path(str(path)+'.versions')
        if self.directory.is_symlink():raise ValueError('KEY_DIRECTORY_SYMLINK_FORBIDDEN')
        self.pattern=pattern
        if not isinstance(embedded,dict):raise ValueError('KEYS_INVALID')
        self.embedded={}
        for ident,value in embedded.items():
            if not isinstance(ident,str) or not pattern.fullmatch(ident):raise ValueError('KEY_VERSION_INVALID')
            self.embedded[ident]=decoded(value)

    def __contains__(self,ident):
        if not isinstance(ident,str) or not self.pattern.fullmatch(ident):return False
        path=self.directory/(ident+'.json')
        return ident in self.embedded or path.is_file() and not path.is_symlink()

    def __iter__(self):
        seen=set(self.embedded)
        yield from self.embedded
        if self.directory.exists():
            if self.directory.is_symlink():raise ValueError('KEY_DIRECTORY_SYMLINK_FORBIDDEN')
            for path in sorted(self.directory.iterdir()):
                ident=path.stem
                if path.suffix=='.json' and self.pattern.fullmatch(ident) and ident not in seen and path.is_file() and not path.is_symlink():
                    seen.add(ident);yield ident

    def __len__(self):
        return sum(1 for _ in self)

    def __getitem__(self,ident):
        if ident in self.embedded:return self.embedded[ident]
        if ident not in self:raise KeyError(ident)
        if self.directory.is_symlink():raise ValueError('KEY_DIRECTORY_SYMLINK_FORBIDDEN')
        return decoded(bounded_json(self.directory/(ident+'.json'),1024)['key'])


def atomic_private(path,data,exclusive=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.is_symlink():raise ValueError('KEY_FILE_SYMLINK_FORBIDDEN')
    temporary=path.with_name(path.name+'.'+secrets.token_hex(8)+'.tmp')
    try:
        fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as stream:
            stream.write(data);stream.flush();os.fsync(stream.fileno())
        if exclusive:
            try:os.link(temporary,path)
            except FileExistsError:
                if path.read_bytes()!=data:raise ValueError('KEY_VERSION_ALREADY_EXISTS')
        else:os.replace(temporary,path)
        if os.name=='posix':
            folder=os.open(path.parent,os.O_RDONLY)
            try:os.fsync(folder)
            finally:os.close(folder)
    finally:temporary.unlink(missing_ok=True)
