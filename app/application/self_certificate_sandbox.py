"""Linux decoder confinement: immutable read allowlist, no network/exec, resource bounds."""
import ctypes, errno, os, platform, sysconfig
from pathlib import Path

class IsolationUnavailable(RuntimeError):
    pass

def clean_environment():
    value={'PATH':'/usr/local/bin:/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1',
        'PYTHONUNBUFFERED':'1','PYTHONUTF8':'1','LANG':'C.UTF-8'}
    # Pinned public resources only; DB credentials and keyring settings are absent.
    if os.environ.get('PX_SELF_CERTIFICATE_RESOURCE_ROOT'):
        value['PX_SELF_CERTIFICATE_RESOURCE_ROOT']=os.environ['PX_SELF_CERTIFICATE_RESOURCE_ROOT']
    return value

def availability():
    if os.name!='posix' or platform.machine() not in ('x86_64','aarch64'):
        return False
    libc=ctypes.CDLL(None,use_errno=True)
    try:ctypes.CDLL('libseccomp.so.2')
    except OSError:return False
    return libc.syscall(444,0,0,1)>=3

def confine(extra_files=()):
    if not availability():
        raise IsolationUnavailable('CERTIFICATE_SANDBOX_UNAVAILABLE')
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(38,1,0,0,0)!=0:
        raise IsolationUnavailable('CERTIFICATE_SANDBOX_UNAVAILABLE')
    class Rules(ctypes.Structure):
        _fields_=[('handled_access_fs',ctypes.c_uint64)]
    class Beneath(ctypes.Structure):
        _pack_=1
        _fields_=[('allowed_access',ctypes.c_uint64),('parent_fd',ctypes.c_int32)]
    rules=Rules((1<<15)-1)  # ABI3: includes REFER and TRUNCATE.
    fd=libc.syscall(444,ctypes.byref(rules),ctypes.sizeof(rules),0)
    if fd<0:raise IsolationUnavailable('CERTIFICATE_SANDBOX_UNAVAILABLE')
    root=Path(__file__).resolve().parents[2]
    # Hosted CI and venv interpreters can keep trusted standard libraries and
    # site-packages outside /usr. Permit those runtime directories, never the
    # project root, private asset store, keyring, or arbitrary sys.path entries.
    runtime_dirs=[Path(sysconfig.get_path(name)) for name in
        ('stdlib','platstdlib','purelib','platlib') if sysconfig.get_path(name)]
    allowed=[*runtime_dirs,Path('/usr'),Path('/lib'),Path('/lib64'),Path('/etc/ld.so.cache'),
        Path('/etc/fonts'),Path('/dev/null'),Path('/dev/urandom'),*map(Path,extra_files)]
    try:
        seen=set()
        for path in allowed:
            if not path.exists():continue
            path=path.resolve()
            if path in seen:continue
            seen.add(path)
            handle=os.open(path,os.O_PATH|os.O_CLOEXEC)
            try:
                access=(1<<2)|((1<<3) if path.is_dir() else 0)
                rule=Beneath(access,handle)
                if libc.syscall(445,fd,1,ctypes.byref(rule),0)!=0:
                    raise IsolationUnavailable('CERTIFICATE_SANDBOX_UNAVAILABLE')
            finally:os.close(handle)
        if libc.syscall(446,fd,0)!=0:
            raise IsolationUnavailable('CERTIFICATE_SANDBOX_UNAVAILABLE')
    finally:os.close(fd)
    # Native-architecture syscall resolution and bad-architecture handling are
    # provided by libseccomp rather than handwritten syscall-number filters.
    sec=ctypes.CDLL('libseccomp.so.2')
    sec.seccomp_init.argtypes=[ctypes.c_uint32];sec.seccomp_init.restype=ctypes.c_void_p
    sec.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];sec.seccomp_syscall_resolve_name.restype=ctypes.c_int
    sec.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint]
    sec.seccomp_load.argtypes=[ctypes.c_void_p]
    sec.seccomp_release.argtypes=[ctypes.c_void_p]
    context=sec.seccomp_init(0x7fff0000)
    if not context:raise IsolationUnavailable('CERTIFICATE_SANDBOX_UNAVAILABLE')
    try:
        denied=('socket','socketpair','connect','bind','listen','accept','accept4',
            'sendto','sendmsg','sendmmsg','recvfrom','recvmsg','recvmmsg',
            'ptrace','process_vm_readv','process_vm_writev','open_by_handle_at',
            'execve','execveat','bpf','userfaultfd','io_uring_setup','perf_event_open',
            'mount','umount2','unshare','setns')
        for name in denied:
            number=sec.seccomp_syscall_resolve_name(name.encode())
            if number>=0 and sec.seccomp_rule_add(context,0x00050000|errno.EPERM,number,0)!=0:
                raise IsolationUnavailable('CERTIFICATE_SANDBOX_UNAVAILABLE')
        if sec.seccomp_load(context)!=0:
            raise IsolationUnavailable('CERTIFICATE_SANDBOX_UNAVAILABLE')
    finally:sec.seccomp_release(context)
