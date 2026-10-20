"""P03 ownership and exception cleanup, runnable on Windows and Linux."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import subprocess
import pytest
from sqlalchemy import event
from app.server import create_app
from harness_support import app_client, ThreadClients, result_file, stop_process


@pytest.mark.parametrize('inject_failure', [False, True], ids=['success', 'batch-exception'])
def test_single_lifespan_closes_sqlite_before_directory_removal(tmp_path, inject_failure):
    folder=tmp_path/'isolated';folder.mkdir()
    app=create_app('sqlite:///'+str(folder/'qa.sqlite'),origin='http://testserver',seed_demo=False)
    disposed=[]
    event.listen(app.state.engine,'engine_disposed',lambda engine:disposed.append(True))
    try:
        with app_client(app) as client:
            with ThreadPoolExecutor(max_workers=4) as pool:
                assert all(r.status_code==200 for r in pool.map(lambda _:client.get('/api/health/ready'),range(16)))
            assert not disposed
            if inject_failure:raise ValueError('injected batch failure')
    except ValueError:
        assert inject_failure
    assert disposed
    for file in folder.iterdir():file.unlink()
    folder.rmdir()
    assert not folder.exists()


def test_thread_clients_close_after_workers_even_on_failure():
    registry=ThreadClients()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _:registry.get('http://testserver'),range(16)))
    clients=list(registry.clients)
    assert clients and all(not c.is_closed for c in clients)
    registry.close()
    assert all(c.is_closed for c in clients)
    assert not registry.clients


def test_output_created_and_traceback_preserved_on_setup_exception(tmp_path):
    output=tmp_path/'missing'/'qa'/'failure.json'
    with pytest.raises(RuntimeError,match='setup injected'):
        with result_file(output):raise RuntimeError('setup injected')
    report=json.loads(output.read_text())
    assert report['status']=='failed' and 'setup injected' in report['traceback']


def test_subprocess_is_reaped_after_failure():
    import sys
    proc=subprocess.Popen([sys.executable,'-c','import time; time.sleep(120)'])
    stop_process(proc)
    assert proc.poll() is not None


def test_admission_resilience_javascript_contract(tmp_path):
    root=Path(__file__).resolve().parents[1]
    run=subprocess.run(['node','--experimental-vm-modules','--test','tests/admission_resilience.mjs'],cwd=root,capture_output=True,text=True,timeout=30)
    out=root/'qa/contracts/admission-resilience.log';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(run.stdout+run.stderr,encoding='utf-8')
    assert run.returncode==0,run.stdout+run.stderr
