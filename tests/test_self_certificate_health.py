"""Capability readiness, existing-file delivery, and bounded private telemetry."""
from pathlib import Path
from fastapi.testclient import TestClient
from tests.test_self_certificate_http import system,new_link,prepare,submit,A,P
from app.application import self_certificate_branding as brand
from app.application import self_certificate_metrics as metrics


def test_missing_logo_changes_readiness_but_not_existing_delivery(system,tmp_path,monkeypatch):
    app,clients=system
    staff=clients()
    link,_=new_link(staff)
    browser,token,prepared=prepare(app,link)
    assert submit(browser,token,prepared).status_code==202
    assert app.state.self_certificate_runtime.generate()
    receive=browser.get(P+'/request/'+token+'/mine').json()['receive_url'].split('/')[-1]
    value=browser.get(P+'/receive/'+receive).json()
    before=browser.get(value['download_url']).content
    assert app.state.self_certificate_runtime.readiness(force=True)['ready']
    monkeypatch.setattr(brand,'LOGO_PATH',tmp_path/'missing-rts.png')
    readiness=app.state.self_certificate_runtime.readiness(force=True)
    assert not readiness['ready']
    assert not readiness['capabilities']['render']['ready']
    assert readiness['capabilities']['delivery']['ready']
    response=staff.get('/api/health/ready')
    assert response.status_code==503
    assert 'missing-rts.png' not in response.text
    assert set(response.json()['certificates'])=={'ready','capabilities','probe_cache_seconds'}
    assert 'free_bytes' not in response.text and 'oldest_age_seconds' not in response.text
    assert browser.get(value['download_url']).content==before
    assert browser.get(P+'/verify/'+value['serial']).json()['status']=='valid'


def test_readiness_marks_absent_workers_and_disabled_new_is_not_delivery_failure(system):
    app,clients=system
    runtime=app.state.self_certificate_runtime
    runtime.background_enabled=True
    runtime.worker_threads=[]
    value=runtime.readiness(force=True)
    assert not value['capabilities']['accept_new']['ready']
    assert value['capabilities']['accept_new']['code']=='CERTIFICATE_WORKERS_UNAVAILABLE'
    assert clients().get('/api/health/live').status_code==200



def test_naive_historical_queue_timestamp_does_not_break_readiness(system):
    from app.self_certificates_db import jobs
    from sqlalchemy import update
    app,clients=system
    link,_=new_link(clients());browser,token,prepared=prepare(app,link)
    assert submit(browser,token,prepared).status_code==202
    with app.state.engine.begin() as conn:
        conn.execute(update(jobs).values(created_at='2000-01-01T00:00:00'))
    value=app.state.self_certificate_runtime.readiness(force=True)
    assert value['queue']['oldest_age_seconds']>120
    assert value['capabilities']['delivery']['ready']
    assert metrics.gauges()['queue_pending']==1


def test_unwritable_slot_monitor_does_not_hide_delivery_capability(system,monkeypatch):
    from app.application import self_certificate_health as health
    app,clients=system
    def unavailable(_):raise PermissionError('synthetic read-only runtime')
    monkeypatch.setattr(health,'active_slots',unavailable)
    value=app.state.self_certificate_runtime.readiness(force=True)
    assert value['capabilities']['delivery']['ready']


def test_forwarded_ip_is_honored_only_for_configured_proxy():
    import asyncio
    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    observed=[]
    async def app(scope,receive,send):observed.append(scope['client'][0])
    wrapped=ProxyHeadersMiddleware(app,trusted_hosts=['10.42.0.2'])
    async def visit(ip):
        scope={'type':'http','scheme':'http','client':(ip,12345),
            'headers':[(b'x-forwarded-for',b'198.51.100.24'),(b'x-forwarded-proto',b'https')]}
        await wrapped(scope,None,None)
    asyncio.run(visit('203.0.113.3'))
    asyncio.run(visit('10.42.0.2'))
    assert observed==['203.0.113.3','198.51.100.24']


def test_telemetry_rejects_arbitrary_labels_and_contains_no_participant_values():
    metrics.record('accepted')
    metrics.record('render',.01)
    import pytest
    with pytest.raises(ValueError):
        metrics.record('phone=0771234567')
    value=metrics.snapshot()
    assert set(value)<=metrics._STAGES
    assert all(set(row)=={'count','seconds_sum','seconds_max'} for row in value.values())
