"""Single-threaded, secret-free renderer supervisor; a fresh confined child per job."""
import argparse, hashlib, json, os, select, signal, socket, struct, sys, threading, time, stat
from pathlib import Path
from app.application.self_certificate_render_worker import render_payload
from app.application.self_certificate_fonts import choices,coverage,font_bytes
MAX_INPUT=200_000
MAX_OUTPUT=80_020_000

def socket_path(root):
    return Path('/tmp')/('px-cert-render-'+hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:24]+'.sock')

def receive(stream,limit):
    def read(size):
        chunks=[];left=size
        while left:
            part=stream.recv(min(left,65536))
            if not part:raise OSError('RENDER_CHANNEL_CLOSED')
            chunks.append(part);left-=len(part)
        return b''.join(chunks)
    size=struct.unpack('!Q',read(8))[0]
    if size>limit:raise OSError('RENDER_CHANNEL_LIMIT')
    return read(size)

def write_fd(fd,data):
    view=memoryview(struct.pack('!Q',len(data))+data)
    while view:
        written=os.write(fd,view)
        if written<=0:raise OSError('RENDER_CHANNEL_CLOSED')
        view=view[written:]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True)
    parser.add_argument('--lock-fd',type=int,required=True)
    args=parser.parse_args()
    root=Path(args.root).resolve()
    path=socket_path(root)
    # Only pinned public resources are preloaded; never DB, keys or participant data.
    for row in choices():
        font_bytes(row['id']);coverage(row['id'])
    if threading.active_count()!=1:raise RuntimeError('RENDER_SUPERVISOR_THREADS_FORBIDDEN')
    server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
    try:
        if path.exists():
            info=path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid!=os.getuid():
                raise RuntimeError('RENDER_CHANNEL_UNAVAILABLE')
            path.unlink()
        server.bind(str(path));os.chmod(path,0o600)
        server.listen(6)
        children={}
        last=time.monotonic()
        while True:
            for pid,started in tuple(children.items()):
                if time.monotonic()-started>30:
                    try:os.kill(pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                try:done,_=os.waitpid(pid,os.WNOHANG)
                except ChildProcessError:done=pid
                if done:children.pop(pid,None)
            readable,_,_=select.select([server],[],[],.5)
            if not readable:
                if not children and time.monotonic()-last>30:return
                continue
            connection,_=server.accept()
            connection.settimeout(2)
            try:
                payload=json.loads(receive(connection,MAX_INPUT))
                if Path(payload['root']).resolve()!=root:raise ValueError('ROOT_INVALID')
                if payload.get('operation')=='shutdown':
                    for child in tuple(children):
                        try:done,_=os.waitpid(child,os.WNOHANG)
                        except ChildProcessError:done=child
                        if done:children.pop(child,None)
                    if children:
                        write_fd(connection.fileno(),b'{"status":"busy"}')
                        continue
                    write_fd(connection.fileno(),b'{"status":"stopped"}')
                    return
                # A client can receive its final bytes just before that child
                # exits. Reap that handoff before rejecting the next slot owner.
                waiting=time.monotonic()+1
                while len(children)>=6 and time.monotonic()<waiting:
                    for child in tuple(children):
                        try:done,_=os.waitpid(child,os.WNOHANG)
                        except ChildProcessError:done=child
                        if done:children.pop(child,None)
                    if len(children)>=6:time.sleep(.005)
                if len(children)>=6:
                    write_fd(connection.fileno(),b'{"error":"CERTIFICATE_RENDER_BUSY"}\n')
                    continue
                pid=os.fork()
                if pid==0:
                    try:
                        server.close()
                        os.close(args.lock_fd)
                        # No ASGI thread, DB connection or secret environment existed here.
                        connection.settimeout(None)
                        output=render_payload(payload)
                        write_fd(connection.fileno(),output)
                    except BaseException:
                        pass
                    finally:os._exit(0)
                children[pid]=time.monotonic()
                last=time.monotonic()
            except (OSError,ValueError,KeyError):
                pass
            finally:connection.close()
    finally:
        server.close()
        path.unlink(missing_ok=True)
        os.close(args.lock_fd)

if __name__=='__main__':
    main()
