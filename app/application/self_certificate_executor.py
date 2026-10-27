"""Bounded framed IPC to a reusable supervisor with fresh resource-limited children."""
import json, os, socket, struct, subprocess, sys, time
from app.application.self_certificate_slots import try_lock
from app.application.self_certificate_sandbox import clean_environment
from app.application.self_certificate_supervisor import socket_path,receive,MAX_OUTPUT
from app.domain import fail

def connect_supervisor(root):
    path=socket_path(root)
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        connection=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        connection.settimeout(30)
        try:
            connection.connect(str(path))
            return connection
        except OSError:
            connection.close()
        fd=try_lock(root/'.runtime'/'supervisor.lock')
        if fd is not None:
            try:
                # The daemon retains this open-file-description lock. Closing
                # the parent's copy does not release the daemon's ownership.
                subprocess.Popen([sys.executable,'-m','app.application.self_certificate_supervisor',
                    '--root',str(root),'--lock-fd',str(fd)],env=clean_environment(),
                    pass_fds=(fd,),stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,start_new_session=True)
            finally:os.close(fd)
        time.sleep(.05)
    fail('CERTIFICATE_RENDER_UNAVAILABLE',503)

def shutdown(root):
    """Explicit isolated maintenance only; never starts a missing supervisor."""
    from pathlib import Path
    path=socket_path(root)
    if not path.exists():return True
    connection=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);connection.settimeout(2)
    try:
        connection.connect(str(path))
        data=json.dumps({'root':str(Path(root).resolve()),'operation':'shutdown'}).encode()
        connection.sendall(struct.pack('!Q',len(data))+data)
        return json.loads(receive(connection,1024)).get('status')=='stopped'
    except OSError:return not path.exists()
    finally:connection.close()


def execute(payload):
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
    if len(encoded)>200_000:fail('CERTIFICATE_RENDER_UNAVAILABLE',503)
    from pathlib import Path
    connection=connect_supervisor(Path(payload['root']))
    try:
        connection.sendall(struct.pack('!Q',len(encoded))+encoded)
        return receive(connection,MAX_OUTPUT)
    except (OSError,ValueError):
        fail('CERTIFICATE_RENDER_UNAVAILABLE',503)
    finally:connection.close()
