"""PulseX entry point: importing this module never changes CWD or touches the database."""
from __future__ import annotations
import uvicorn
import os
from app.core.build_info import APP_NAME, BUILD_LABEL
from app.core.settings import load_settings
from tools.production_gate import assert_production_ready

def main() -> None:
    settings = load_settings(local_launcher=True)
    if settings.workers > 1 and settings.seed_demo:
        raise RuntimeError("MULTI_WORKER_REQUIRES_SEED_DEMO_FALSE")
    if settings.production_mode:
        assert_production_ready(database_url=settings.database_url,
                                origin=settings.public_origin,
                                seed_demo=settings.seed_demo, workers=settings.workers)
    print(f"{APP_NAME} {BUILD_LABEL} | workers={settings.workers} | seed_demo={settings.seed_demo}", flush=True)
    trusted=os.environ.get('FORWARDED_ALLOW_IPS','127.0.0.1').strip()
    if settings.production_mode and '*' in trusted:
        raise RuntimeError('TRUSTED_PROXY_WILDCARD_FORBIDDEN')
    opts=dict(host=settings.host,port=settings.port,access_log=False,timeout_graceful_shutdown=30,
              proxy_headers=True,forwarded_allow_ips=trusted)
    if settings.workers > 1:
        uvicorn.run("app.server:create_app",factory=True,workers=settings.workers,**opts)
    else:
        from app.server import create_app
        app=create_app(database_url=settings.database_url,origin=settings.public_origin,
                       seed_demo=settings.seed_demo,credentials_path=settings.credentials_path)
        uvicorn.run(app,**opts)

if __name__ == "__main__":
    main()
