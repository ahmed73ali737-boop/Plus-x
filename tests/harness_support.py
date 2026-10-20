"""Explicit ownership for disposable QA resources; never touches a live database."""
from contextlib import contextmanager
from pathlib import Path
import json
import subprocess
import threading
import traceback
from fastapi.testclient import TestClient
import httpx


@contextmanager
def app_client(app):
    """One lifespan for the whole batch, including exception and enter-failure cleanup."""
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.state.engine.dispose()


class ThreadClients:
    """Close only after the executor has joined; each worker retains its own client."""
    def __init__(self):
        self.local = threading.local()
        self.clients = []
        self.lock = threading.Lock()

    def get(self, base, timeout=30):
        client = getattr(self.local, 'client', None)
        if client is None:
            client = httpx.Client(base_url=base, timeout=timeout, trust_env=False,
                                 limits=httpx.Limits(max_keepalive_connections=8, max_connections=16))
            self.local.client = client
            with self.lock:
                self.clients.append(client)
        return client

    def close(self):
        with self.lock:
            clients, self.clients = self.clients, []
        try:
            for client in clients:
                client.close()
        finally:
            self.local = threading.local()


@contextmanager
def result_file(path):
    """A failed setup/batch still leaves a failing report; the exception propagates."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'failed'}
    try:
        yield report
    except BaseException:
        report.update(status='failed', traceback=traceback.format_exc())
        raise
    finally:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def stop_process(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
