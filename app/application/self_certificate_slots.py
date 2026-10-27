"""Kernel-released cross-process slots for one shared certificate filesystem."""
from contextlib import contextmanager
import os, time
try:import fcntl
except ImportError:fcntl=None
from pathlib import Path
from app.domain import fail

def try_lock(path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_CREAT|os.O_RDWR|getattr(os,'O_CLOEXEC',0),0o600)
    try:
        if fcntl is not None:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        else:
            import msvcrt
            if os.fstat(fd).st_size==0:os.write(fd,b'\0')
            os.lseek(fd,0,os.SEEK_SET)
            msvcrt.locking(fd,msvcrt.LK_NBLCK,1)
        return fd
    except (BlockingIOError,PermissionError):
        os.close(fd)
        return None

def active_slots(root,limit=6):
    occupied=0
    for number in range(limit):
        fd=try_lock(Path(root)/'.runtime'/('render-'+str(number)+'.lock'))
        if fd is None:occupied+=1
        else:os.close(fd)
    return occupied


@contextmanager
def render_slot(root,limit=6,timeout=5):
    if not 1<=limit<=6:raise ValueError('INVALID_SELF_CERTIFICATE_RENDER_CONCURRENCY')
    deadline=time.monotonic()+timeout
    fd=None
    while fd is None:
        for number in range(limit):
            fd=try_lock(Path(root)/'.runtime'/('render-'+str(number)+'.lock'))
            if fd is not None:break
        if fd is not None:break
        if time.monotonic()>=deadline:fail('CERTIFICATE_RENDER_BUSY',429)
        time.sleep(.025)
    try:yield
    finally:os.close(fd)
