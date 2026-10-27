"""Capability readiness; saved downloads do not require current render resources."""
import hashlib, importlib.util, logging, os, secrets, threading, time, shutil
from pathlib import Path
from sqlalchemy import select,func
from fastapi import HTTPException
from app.self_certificates_db import links, certificates,jobs,exports
from app.application.self_certificate_clock import lease_now
from app.application.self_certificate_slots import active_slots
from app.application import self_certificate_metrics as metrics
from datetime import datetime,timezone
from app.core.certificate_features import certificate_features
from app.application import self_certificate_fonts as fonts, self_certificate_branding as brand

log=logging.getLogger(__name__)


class CertificateReadiness:
    def __init__(self, engine, store, keys, runtime):
        self.engine,self.store,self.keys,self.runtime=engine,store,keys,runtime
        self._lock=threading.Lock()
        self._at=0.0
        self._value=None
        self._alerts=set()
        self.minimum_free=int(os.environ.get('PX_SELF_CERTIFICATE_MIN_FREE_BYTES','268435456'))
        if not 0<=self.minimum_free<=100*1024**4:raise RuntimeError('INVALID_CERTIFICATE_STORAGE_RESERVE')

    def __call__(self, force=False):
        with self._lock:
            if not force and self._value is not None and time.monotonic()-self._at<5:
                return self._value
            value=self._probe()
            old=(self._value or {}).get('capabilities',{})
            for name,entry in value['capabilities'].items():
                if old.get(name,{}).get('ready')!=entry['ready']:
                    log.warning('SELF_CERTIFICATE_CAPABILITY_CHANGED capability=%s ready=%s code=%s',
                        name,entry['ready'],entry['code'])
            alerts=set()
            if value.get('queue',{}).get('oldest_age_seconds',0)>120:alerts.add('QUEUE_STALE')
            if value.get('queue',{}).get('failed_jobs',0)>0:alerts.add('GENERATION_FAILURES')
            if value.get('storage',{}).get('free_bytes',0)<self.minimum_free:alerts.add('STORAGE_LOW')
            if value['capabilities']['accept_new']['required'] and not value['capabilities']['accept_new']['ready']:alerts.add('ACCEPTANCE_UNAVAILABLE')
            for code in alerts-self._alerts:log.warning('SELF_CERTIFICATE_ALERT code=%s state=active',code)
            for code in self._alerts-alerts:log.warning('SELF_CERTIFICATE_ALERT code=%s state=recovered',code)
            self._alerts=alerts
            self._value=value
            self._at=time.monotonic()
            return value

    def _probe(self):
        features=certificate_features()
        accepting=features.accept_new_requests
        designing=features.admin_enabled
        with self.engine.connect() as conn:
            has_history=bool(conn.execute(select(links.c.id).limit(1)).first()
                or conn.execute(select(certificates.c.id).limit(1)).first())
            key_versions=conn.execute(select(links.c.key_version).union(select(certificates.c.key_version))).scalars().all()
            queue=dict(conn.execute(select(jobs.c.status,func.count()).group_by(jobs.c.status)).all())
            pending=sum(queue.get(status,0) for status in ('pending','retry_wait','leased'))
            oldest=conn.execute(select(func.min(jobs.c.created_at)).where(jobs.c.status.in_(('pending','retry_wait','leased')))).scalar_one()
            queue_age=0
            if oldest:
                try:
                    now_value=datetime.fromisoformat(lease_now(conn))
                    oldest_value=datetime.fromisoformat(oldest)
                    if now_value.tzinfo is None:now_value=now_value.replace(tzinfo=timezone.utc)
                    if oldest_value.tzinfo is None:oldest_value=oldest_value.replace(tzinfo=timezone.utc)
                    queue_age=max(0,(now_value-oldest_value).total_seconds())
                except (ValueError,TypeError):
                    # Corrupt historical time must alert without crashing delivery health.
                    queue_age=121
                    log.warning('SELF_CERTIFICATE_QUEUE_TIMESTAMP_INVALID')
            export_pending=conn.execute(select(func.count()).select_from(exports).where(exports.c.status.in_(('pending','processing')))).scalar_one()
        metrics.gauge('failed_jobs',queue.get('failed',0))
        try:metrics.gauge('active_slots',active_slots(self.store.root))
        except OSError:
            # A read-only runtime directory cannot prevent delivery diagnosis.
            metrics.gauge('active_slots',0)
        metrics.gauge('queue_age_seconds',queue_age)
        metrics.gauge('queue_pending',pending)
        metrics.gauge('export_pending',export_pending)
        readable=os.access(self.store.root,os.R_OK|os.X_OK)
        storage_code='OK'
        writable=True
        free_bytes=0
        probe=self.store.root/('.probe-'+secrets.token_hex(12))
        target=probe.with_suffix('.ready')
        try:
            # A tiny actual atomic write catches read-only/full filesystems.
            with probe.open('xb') as stream:
                os.chmod(probe,0o600)
                stream.write(b'certificate-readiness')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(probe,target)
            free_bytes=shutil.disk_usage(self.store.root).free
            if free_bytes<self.minimum_free:raise OSError('STORAGE_RESERVE_EXHAUSTED')
        except OSError:
            writable=False
            storage_code='CERTIFICATE_STORAGE_UNAVAILABLE'
        finally:
            for path in (probe,target):
                try:path.unlink(missing_ok=True)
                except OSError:pass
        metrics.gauge('storage_free_bytes',free_bytes)
        key_ok=True
        if self.keys_path_exists() or has_history:
            try:
                keyring=self.keys()
                for version in key_versions:keyring.sign('readiness','pinned-resource',version)
            except HTTPException:key_ok=False
        resource_ok=True
        resource_code='OK'
        try:
            raw=(fonts.ROOT/'noto-manifest.json').read_bytes()
            if hashlib.sha256(raw).hexdigest()!=fonts.MANIFEST_HASH:
                raise RuntimeError('FONT_CATALOG_UNAVAILABLE')
            import json
            for row in json.loads(raw):
                content=(fonts.ROOT/(row['sha256']+'.ttf')).read_bytes()
                if hashlib.sha256(content).hexdigest()!=row['sha256']:
                    raise RuntimeError('FONT_FILE_UNAVAILABLE')
            brand.verified_bytes(brand.LOGO_PATH,brand.LOGO_SHA256,'BRANDING_ASSET_UNAVAILABLE')
            brand.verified_bytes(brand.FONT_PATH,brand.FONT_SHA256,'BRANDING_FONT_UNAVAILABLE')
            from app.application.self_certificate_sandbox import availability
            if not availability() or importlib.util.find_spec('resource') is None or importlib.util.find_spec('pypdfium2') is None:
                raise RuntimeError('CERTIFICATE_ISOLATION_UNAVAILABLE')
        except (OSError,ValueError,KeyError,RuntimeError,HTTPException) as error:
            resource_ok=False
            resource_code=(error.detail if isinstance(error,HTTPException) else str(error) if isinstance(error,RuntimeError) else 'CERTIFICATE_RESOURCE_UNAVAILABLE')
        worker_required=bool(getattr(self.runtime,'background_enabled',False))
        threads=getattr(self.runtime,'worker_threads',())
        worker_ok=not worker_required or bool(threads) and all(t.is_alive() for t in threads)
        if hasattr(self.runtime,'workers_ready'):
            worker_ok=not worker_required or self.runtime.workers_ready()
        def cap(ready,required,code='OK'):
            return {'ready':bool(ready),'required':bool(required),'code':code if not ready else 'OK'}
        render_ok=resource_ok and writable
        capabilities={
            'render':cap(render_ok,designing or accepting or pending>0,resource_code if not resource_ok else storage_code),
            'accept_new':cap(accepting and render_ok and worker_ok and key_ok,accepting,
                'CERTIFICATE_REQUESTS_PAUSED' if not accepting else resource_code if not resource_ok else storage_code if not writable else 'CERTIFICATE_WORKERS_UNAVAILABLE' if not worker_ok else 'CERTIFICATE_KEYS_UNAVAILABLE'),
            'delivery':cap(readable and key_ok,has_history,'CERTIFICATE_KEYS_UNAVAILABLE' if not key_ok else 'CERTIFICATE_STORAGE_UNAVAILABLE'),
            'export':cap(writable and worker_ok,has_history,storage_code if not writable else 'CERTIFICATE_WORKERS_UNAVAILABLE'),
        }
        return {'ready':all(v['ready'] for v in capabilities.values() if v['required']),
            'capabilities':capabilities,'probe_cache_seconds':5,
            'queue':{'pending':pending,'oldest_age_seconds':queue_age,'export_pending':export_pending,'failed_jobs':queue.get('failed',0)},
            'storage':{'free_bytes':free_bytes,'minimum_free_bytes':self.minimum_free}}

    def keys_path_exists(self):
        return bool(getattr(self.runtime,'keypath',Path('/nonexistent-keyring')).exists())
