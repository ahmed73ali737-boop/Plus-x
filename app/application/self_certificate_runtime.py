"""One elected worker service across ASGI processes sharing the private store."""
import json,logging,os,threading,time
from pathlib import Path
from app.application.self_certificate_slots import try_lock
log=logging.getLogger(__name__)

class CertificateWorkers:
    def __init__(self,engine,runtime,legacy,count=6):
        if not 1<=count<=6:raise RuntimeError('INVALID_SELF_CERTIFICATE_WORKERS')
        self.engine,self.runtime,self.legacy,self.count=engine,runtime,legacy,count
        self.stop=threading.Event()
        self.generators=[]
        self.maintenance=None
        self.leader=None
        self.coordinator=None
        self.directory=Path(runtime.store.root)/'.runtime'
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        runtime.workers_ready=self.ready

    def ready(self):
        try:
            data=json.loads((self.directory/'heartbeat.json').read_text())
            age=time.monotonic()-data['monotonic']
            return data['worker_count']==self.count and 0<=age<5
        except (OSError,ValueError,KeyError,TypeError):return False

    def _heartbeat(self):
        target=self.directory/'heartbeat.json'
        temporary=self.directory/('heartbeat-'+str(os.getpid())+'.tmp')
        with temporary.open('w') as stream:
            os.chmod(temporary,0o600)
            json.dump({'monotonic':time.monotonic(),'worker_count':self.count},stream)
        os.replace(temporary,target)

    def _generate(self):
        while not self.stop.is_set():
            try:
                if not self.runtime.generate():self.stop.wait(.25)
            except Exception:
                log.warning('SELF_CERTIFICATE_WORKER_RETRY')
                self.stop.wait(1)

    def _maintain(self):
        last_legacy=last_expiry=last_cleanup=0.
        while not self.stop.wait(.25):
            try:
                if time.monotonic()-last_legacy>=1:
                    self.legacy()
                    last_legacy=time.monotonic()
                self.runtime.export()
                if time.monotonic()-last_expiry>=60:
                    self.runtime.expire_exports()
                    last_expiry=time.monotonic()
                if time.monotonic()-last_cleanup>=3600:
                    self.runtime.cleanup_assets()
                    last_cleanup=time.monotonic()
            except Exception:
                log.warning('SELF_CERTIFICATE_MAINTENANCE_RETRY')
                self.stop.wait(1)

    def _coordinate(self):
        try:
            while not self.stop.wait(.25):
                if self.leader is None:
                    self.leader=try_lock(self.directory/'workers.lock')
                    if self.leader is None:continue
                    self.generators=[None]*self.count
                for index,thread in enumerate(self.generators):
                    if thread is None or not thread.is_alive():
                        thread=threading.Thread(target=self._generate,name='self-certificate-'+str(index+1),daemon=True)
                        self.generators[index]=thread
                        thread.start()
                if self.maintenance is None or not self.maintenance.is_alive():
                    self.maintenance=threading.Thread(target=self._maintain,name='certificate-maintenance',daemon=True)
                    self.maintenance.start()
                self._heartbeat()
        finally:
            # Keep leadership until all owned workers stop; never elect an
            # overlapping group merely because HTTP shutdown has started.
            for thread in [*self.generators,self.maintenance]:
                if thread is not None:thread.join()
            if self.leader is not None:
                os.close(self.leader)
                self.leader=None

    def start(self):
        self.coordinator=threading.Thread(target=self._coordinate,name='certificate-coordinator',daemon=True)
        self.coordinator.start()

    def close(self):
        self.stop.set()
        if self.coordinator:self.coordinator.join(timeout=35)
