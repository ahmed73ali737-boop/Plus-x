"""Device enrolment, administration, authentication and heartbeat use cases."""
from __future__ import annotations

from app.application import access
from app.application.audit_service import new_id
from app.application.ports import persistence
from app.core.security import digest
from app.domain import NotFound, Unauthenticated, fail, now, text
from app.domain.devices import (
    DEVICE_STATUSES,
    DEVICE_TYPES,
    device_changes,
    device_type,
    heartbeat_values,
    require_gate_device,
    require_usable,
    validate_device_metadata,
)

__all__ = [
    'DEVICE_STATUSES', 'DEVICE_TYPES', 'authenticate_device', 'authenticate_gate_device', 'create_device',
    'heartbeat', 'list_devices', 'site_device', 'update_device', 'validate_device_metadata',
]


def create_device(tx, site_id: str, name: str, kind: str, token: str, app_version: str = '',
                  metadata_json: dict | None = None):
    kind = device_type(kind)
    device_id = new_id()
    persistence.devices.add(tx, {
        'id': device_id,
        'site_id': site_id,
        'name': text(name, 160, True),
        'device_type': kind,
        'token_hash': digest(token),
        'status': 'active',
        'last_seen_at': None,
        'last_sync_at': None,
        'pending_count': 0,
        'app_version': text(app_version, 40),
        'metadata_json': validate_device_metadata({} if metadata_json is None else metadata_json),
        'created_at': now(),
    })
    return device_id


def list_devices(tx, site_id: str):
    return [{key: value for key, value in row.items() if key != 'token_hash'}
            for row in persistence.devices.for_site(tx, site_id)]


def site_device(tx, site_id: str, device_id: str) -> dict:
    device = persistence.devices.get(tx, device_id)
    if not device or device['site_id'] != site_id:
        fail('DEVICE_NOT_FOUND', NotFound)
    return device


def update_device(tx, device_id: str, *, status=None, name=None, app_version=None, metadata_json=None):
    device = persistence.devices.get(tx, device_id, for_update=True)
    if not device:
        fail('DEVICE_NOT_FOUND', NotFound)
    values = device_changes(status=status, name=name, app_version=app_version, metadata_json=metadata_json)
    persistence.devices.update(tx, device_id, values)
    return {**device, **values}


def authenticate_device(tx, raw_token: str, *, for_update: bool = False):
    if not raw_token:
        fail('DEVICE_TOKEN_REQUIRED', Unauthenticated)
    device = persistence.devices.by_token_hash(tx, digest(raw_token), for_update=for_update)
    # Shift windows use the same authorization clock as staff assignments.
    return require_usable(device, access.now())


def authenticate_gate_device(tx, raw_token: str, event_id: str):
    return require_gate_device(authenticate_device(tx, raw_token), event_id)


def heartbeat(tx, raw_token: str, body: dict):
    device = authenticate_device(tx, raw_token, for_update=True)
    values = heartbeat_values(device, body, now())
    persistence.devices.update(tx, device['id'], values)
    return {'id': device['id'], 'site_id': device['site_id'], 'status': 'ok', **values}
