"""Field devices (kiosks, tablets, displays, gate operators) and their policy."""
from __future__ import annotations

import math
from datetime import datetime

from app.domain.authorization import active_window
from app.domain.errors import Forbidden, NotFound, Unauthenticated, fail
from app.domain.values import CODE, stamp, text

DEVICE_TYPES = ('kiosk', 'tablet', 'display', 'operator')
DEVICE_STATUSES = ('active', 'disabled', 'retired')
GATE_DEVICE_TYPE = 'operator'
MAX_PENDING = 1_000_000
TELEMETRY_TEXT_FIELDS = (('browser', 160), ('user_agent', 500))


def validate_device_metadata(value) -> dict:
    """Administrative device policy: allowed checkpoints and an optional shift window."""
    if not isinstance(value, dict):
        fail('DEVICE_METADATA_INVALID')
    result = dict(value)
    if 'checkpoints' in result:
        checkpoints = result['checkpoints']
        if (not isinstance(checkpoints, list) or len(checkpoints) > 100
                or any(not isinstance(key, str) or len(key) > 40 or not CODE.fullmatch(key) for key in checkpoints)
                or len(checkpoints) != len(set(checkpoints))):
            fail('DEVICE_CHECKPOINTS_INVALID')
    for key in ('valid_from', 'valid_until'):
        if key in result:
            result[key] = stamp(result[key]) or None
    start, end = result.get('valid_from'), result.get('valid_until')
    if start and end and (datetime.fromisoformat(start.replace('Z', '+00:00'))
                          >= datetime.fromisoformat(end.replace('Z', '+00:00'))):
        fail('DEVICE_SHIFT_WINDOW_INVALID')
    return result


def device_type(value) -> str:
    if value not in DEVICE_TYPES:
        fail('DEVICE_TYPE_INVALID')
    return value


def device_changes(*, status=None, name=None, app_version=None, metadata_json=None) -> dict:
    values = {}
    if status is not None:
        if status not in DEVICE_STATUSES:
            fail('DEVICE_STATUS_INVALID')
        values['status'] = status
    if name is not None:
        values['name'] = text(name, 160, True)
    if app_version is not None:
        values['app_version'] = text(app_version, 40)
    if metadata_json is not None:
        values['metadata_json'] = validate_device_metadata(metadata_json)
    if not values:
        fail('NO_CHANGES')
    return values


def require_usable(device: dict | None, at: str | None = None) -> dict:
    """A bearer device token works only while the device is active and on shift (at ``at``)."""
    if not device or device['status'] != 'active':
        fail('DEVICE_TOKEN_INVALID', Unauthenticated)
    metadata = device['metadata_json']
    if not isinstance(metadata, dict) or not active_window({
        'status': 'active', 'valid_from': metadata.get('valid_from'), 'valid_until': metadata.get('valid_until'),
    }, at):
        fail('DEVICE_SHIFT_INACTIVE', Unauthenticated)
    return device


def require_gate_device(device: dict, event_id: str) -> dict:
    if device['site_id'] != event_id:
        fail('DEVICE_EVENT_SCOPE', Forbidden)
    if device['device_type'] != GATE_DEVICE_TYPE:
        fail('DEVICE_GATE_PERMISSION', Forbidden)
    return device


def heartbeat_values(device: dict, body: dict, at: str) -> dict:
    """Telemetry a device may report about itself; it can never change its policy."""
    pending = body.get('pending_count', 0)
    if (isinstance(pending, bool) or not isinstance(pending, (int, float)) or not math.isfinite(pending)
            or pending < 0 or pending > MAX_PENDING):
        fail('DEVICE_PENDING_INVALID')
    values = {
        'last_seen_at': at,
        'pending_count': int(pending),
        'app_version': text(body.get('app_version') or device.get('app_version'), 40),
    }
    if body.get('synced') is True:
        values['last_sync_at'] = values['last_seen_at']
    metadata = body.get('metadata')
    if metadata is not None:
        if not isinstance(metadata, dict):
            fail('DEVICE_METADATA_INVALID')
        # Preserve administrative scope and shift metadata even when the client
        # submits an empty object or forged policy fields.
        telemetry = {}
        for key, maximum in TELEMETRY_TEXT_FIELDS:
            if key in metadata:
                telemetry[key] = text(metadata[key], maximum)
        if 'kiosk' in metadata:
            if not isinstance(metadata['kiosk'], bool):
                fail('DEVICE_KIOSK_BOOLEAN_REQUIRED')
            telemetry['kiosk'] = metadata['kiosk']
        values['metadata_json'] = {**device['metadata_json'], **telemetry}
    return values


def require_device_of_site(device: dict | None, site_id: str) -> dict:
    """A device of another site does not exist for this site's managers."""
    if not device or device['site_id'] != site_id:
        fail('DEVICE_NOT_FOUND', NotFound)
    return device


def require_device(device: dict | None) -> dict:
    if not device:
        fail('DEVICE_NOT_FOUND', NotFound)
    return device


def require_device_token(raw_token) -> str:
    if not raw_token:
        fail('DEVICE_TOKEN_REQUIRED', Unauthenticated)
    return raw_token
