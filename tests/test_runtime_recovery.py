"""Health contract regressions; Docker recovery is a separate acceptance gate."""
import json
from pathlib import Path
import pytest
from sqlalchemy import text
from app.server import create_app
from harness_support import app_client
from tools import app_healthcheck


def test_live_independent_of_database_and_ready_recovers(tmp_path, monkeypatch):
    app=create_app('sqlite:///'+str(tmp_path/'health.sqlite'),seed_demo=False)
    engine=app.state.engine
    connect=engine.connect
    with app_client(app) as client:
        assert client.get('/api/health/ready').status_code==200
        def down():raise OSError('password=must-not-appear')
        monkeypatch.setattr(engine,'connect',down)
        assert client.get('/api/health/live').status_code==200
        response=client.get('/api/health/ready')
        assert response.status_code==503
        assert response.json()['reason']=='DATABASE_UNAVAILABLE'
        assert 'must-not-appear' not in response.text
        monkeypatch.setattr(engine,'connect',connect)
        assert client.get('/api/health/ready').status_code==200
        with engine.begin() as c:c.execute(text('DROP TABLE px_event_guests'))
        response=client.get('/api/health/ready')
        assert response.status_code==503 and 'SCHEMA_TABLES_MISSING' in response.text


@pytest.mark.parametrize('payload,exit_code',[({'status':'ready'},0),({'status':'not_ready'},1)])
def test_stdlib_probe_requires_explicit_readiness(monkeypatch,payload,exit_code):
    import io
    class Response(io.BytesIO):status=200
    monkeypatch.setattr(app_healthcheck.urllib.request,'urlopen',lambda *a,**k:Response(json.dumps(payload).encode()))
    assert app_healthcheck.main()==exit_code


def test_probe_fails_on_transport_error(monkeypatch):
    def down(*a,**k):raise OSError('down')
    monkeypatch.setattr(app_healthcheck.urllib.request,'urlopen',down)
    assert app_healthcheck.main()==1


def test_recovery_subnet_handles_null_ipam_and_excludes_existing_networks():
    import ipaddress
    from runtime_recovery_acceptance import recovery_subnet
    networks=[{'IPAM':{'Config':None}},{'IPAM':None},
              {'IPAM':{'Config':[{'Subnet':'10.233.0.0/17'},{'Subnet':'fd00::/64'}]}}]
    chosen=ipaddress.ip_network(recovery_subnet(networks))
    assert chosen.subnet_of(ipaddress.ip_network('10.233.128.0/17'))
    with pytest.raises(RuntimeError,match='NO_ISOLATED_RECOVERY_SUBNET'):
        recovery_subnet([{'IPAM':{'Config':[{'Subnet':'10.233.0.0/16'}]}}])
