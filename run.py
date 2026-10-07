import os
from pathlib import Path
import uvicorn
from app.server import create_app
from app.core.build_info import APP_NAME, BUILD_LABEL
from tools.production_gate import assert_production_ready

root=Path(__file__).resolve().parent
os.chdir(root)
seed_demo=os.environ.get('SEED_DEMO','true').lower()=='true'
workers=max(1,int(os.environ.get('WEB_WORKERS','1')))
host=os.environ.get('HOST','127.0.0.1')
port=int(os.environ.get('PORT','4310'))
credentials=os.environ.get('CREDENTIALS_PATH','data/first-run-accounts.json')
production_mode=(
    os.environ.get('PULSEX_ENV','').strip().lower()=='production'
    or os.environ.get('REQUIRE_POSTGRES','false').lower()=='true'
)
if production_mode:
    assert_production_ready()

# Local/supervised mode uses an in-process app so demo account generation remains deterministic.
# Production scale mode uses Uvicorn's import-string factory, which is required for multiple workers.
if workers > 1 and not seed_demo:
    app=None
else:
    app=create_app(seed_demo=seed_demo,credentials_path=credentials)

if __name__=='__main__':
    print(f'{APP_NAME} {BUILD_LABEL} | workers={workers} | seed_demo={seed_demo}')
    if workers > 1:
        if seed_demo:
            raise RuntimeError('MULTI_WORKER_REQUIRES_SEED_DEMO_FALSE')
        uvicorn.run('app.server:create_app',factory=True,host=host,port=port,workers=workers,access_log=False)
    else:
        uvicorn.run(app,host=host,port=port,access_log=False)
