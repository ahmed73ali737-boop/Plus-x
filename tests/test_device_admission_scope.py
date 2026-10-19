"""Device telemetry cannot mutate administrative admission restrictions."""
import pytest
from fastapi import HTTPException
from sqlalchemy import insert, select, update

from app.application.device_service import authenticate_device, create_device, heartbeat, update_device
from app.db import devices, make_engine, metadata, sites
from app.domain import default_config


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setattr('app.application.access.now', lambda: '2026-10-19T12:00:00+00:00')
    engine = make_engine('sqlite:///:memory:')
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(sites).values(id='event-a', slug='event-a', kind='event', event_id='event-a', draft=default_config('Event', 'event'), draft_rev=1, published_version=0))
        yield connection
    engine.dispose()


def make_device(conn, policy=None):
    return create_device(conn, 'event-a', 'Scanner', 'operator', 'device-secret', metadata_json=policy)


def test_heartbeat_cannot_erase_or_override_checkpoint_and_shift_scope(conn):
    policy = {'checkpoints': ['vip'], 'valid_from': '2026-10-19T11:00:00+00:00',
              'valid_until': '2026-10-19T13:00:00+00:00', 'admin_label': 'Restricted'}
    device_id = make_device(conn, policy)
    heartbeat(conn, 'device-secret', {'metadata': {}})
    assert authenticate_device(conn, 'device-secret')['metadata_json'] == policy
    heartbeat(conn, 'device-secret', {'metadata': {
        'checkpoints': None, 'valid_from': None, 'valid_until': None, 'admin_label': 'Owned',
        'browser': 'Firefox', 'user_agent': 'Scanner/1.0', 'kiosk': True,
    }})
    metadata = authenticate_device(conn, 'device-secret')['metadata_json']
    assert metadata == {**policy, 'browser': 'Firefox', 'user_agent': 'Scanner/1.0', 'kiosk': True}
    # Administrators retain the authority to deliberately change restrictions.
    update_device(conn, device_id, metadata_json={'checkpoints': ['main']})
    heartbeat(conn, 'device-secret', {'metadata': {'checkpoints': ['vip'], 'browser': 'Edge'}})
    assert authenticate_device(conn, 'device-secret')['metadata_json'] == {'checkpoints': ['main'], 'browser': 'Edge'}


@pytest.mark.parametrize('checkpoints', [None, 'main', ['main', 'main'], ['../main'], [False], [[]], ['x'*41], ['p'+str(n) for n in range(101)]])
def test_create_rejects_invalid_checkpoint_policy(conn, checkpoints):
    with pytest.raises(HTTPException) as exc:
        make_device(conn, {'checkpoints': checkpoints})
    assert exc.value.status_code == 422
    assert not conn.execute(select(devices)).first()


def test_empty_checkpoint_list_is_preserved_as_explicit_deny_all(conn):
    make_device(conn, {'checkpoints': []})
    heartbeat(conn, 'device-secret', {'metadata': {'browser': 'Edge', 'checkpoints': ['main']}})
    assert authenticate_device(conn, 'device-secret')['metadata_json']['checkpoints'] == []


def test_invalid_admin_update_does_not_erase_previous_policy(conn):
    device_id = make_device(conn, {'checkpoints': ['vip']})
    with pytest.raises(HTTPException):
        update_device(conn, device_id, metadata_json={'checkpoints': 'all'})
    assert authenticate_device(conn, 'device-secret')['metadata_json']['checkpoints'] == ['vip']


@pytest.mark.parametrize('policy', [
    {'valid_until': '2026-10-19T12:00:00+00:00'},
    {'valid_from': '2026-10-19T12:00:01+00:00'},
])
def test_expired_or_future_device_shift_rejects_token_and_heartbeat(conn, policy):
    make_device(conn, policy)
    for operation in (lambda: authenticate_device(conn, 'device-secret'), lambda: heartbeat(conn, 'device-secret', {'metadata': {'valid_until': None}})):
        with pytest.raises(HTTPException) as exc:
            operation()
        assert exc.value.status_code == 401 and exc.value.detail == 'DEVICE_SHIFT_INACTIVE'


def test_device_shift_compares_instants_across_timezone_offsets(conn):
    make_device(conn, {'valid_from': '2026-10-19T15:00:00+03:00', 'valid_until': '2026-10-19T16:00:00+03:00'})
    assert authenticate_device(conn, 'device-secret')['status'] == 'active'


@pytest.mark.parametrize('policy', [
    {'valid_from': '2026-10-19T12:00:00'},
    {'valid_until': 'tomorrow'},
    {'valid_from': '2026-10-19T14:00:00+00:00', 'valid_until': '2026-10-19T13:00:00+00:00'},
])
def test_admin_rejects_invalid_or_reversed_shift(conn, policy):
    with pytest.raises(HTTPException) as exc:
        make_device(conn, policy)
    assert exc.value.status_code == 422


def test_legacy_invalid_shift_fails_closed_and_unrestricted_legacy_device_still_works(conn):
    device_id = make_device(conn)
    assert authenticate_device(conn, 'device-secret')['metadata_json'] == {}
    conn.execute(update(devices).where(devices.c.id == device_id).values(metadata_json={'valid_until': 'bad-time'}))
    with pytest.raises(HTTPException) as exc:
        authenticate_device(conn, 'device-secret')
    assert exc.value.status_code == 401


def test_invalid_telemetry_is_rejected_without_scope_changes(conn):
    make_device(conn, {'checkpoints': ['vip']})
    for body in ({'pending_count': float('nan')}, {'pending_count': float('inf')}, {'metadata': {'kiosk': 'false'}}):
        with pytest.raises(HTTPException) as exc:
            heartbeat(conn, 'device-secret', body)
        assert exc.value.status_code == 422
    assert authenticate_device(conn, 'device-secret')['metadata_json'] == {'checkpoints': ['vip']}
