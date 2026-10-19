from __future__ import annotations

from datetime import datetime
import math

from sqlalchemy import insert, select, update

from app.core.security import digest
from app.domain import CODE, fail, now, stamp, text
from app.db import devices
from app.application.access import active_window
from app.application.audit_service import new_id

DEVICE_TYPES = ('kiosk','tablet','display','operator')
DEVICE_STATUSES = ('active','disabled','retired')


def validate_device_metadata(value):
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
    if start and end and datetime.fromisoformat(start.replace('Z', '+00:00')) >= datetime.fromisoformat(end.replace('Z', '+00:00')):
        fail('DEVICE_SHIFT_WINDOW_INVALID')
    return result


def create_device(conn, site_id: str, name: str, device_type: str, token: str, app_version: str = '', metadata_json: dict | None = None):
    if device_type not in DEVICE_TYPES:
        fail('DEVICE_TYPE_INVALID')
    did = new_id()
    conn.execute(insert(devices).values(
        id=did,
        site_id=site_id,
        name=text(name,160,True),
        device_type=device_type,
        token_hash=digest(token),
        status='active',
        last_seen_at=None,
        last_sync_at=None,
        pending_count=0,
        app_version=text(app_version,40),
        metadata_json=validate_device_metadata({} if metadata_json is None else metadata_json),
        created_at=now(),
    ))
    return did


def list_devices(conn, site_id: str):
    rows=conn.execute(select(devices).where(devices.c.site_id==site_id).order_by(devices.c.created_at.desc())).mappings()
    return [{k:v for k,v in dict(x).items() if k!='token_hash'} for x in rows]


def update_device(conn, device_id: str, *, status=None, name=None, app_version=None, metadata_json=None):
    d=conn.execute(select(devices).where(devices.c.id==device_id).with_for_update()).mappings().first()
    if not d: fail('DEVICE_NOT_FOUND',404)
    values={}
    if status is not None:
        if status not in DEVICE_STATUSES: fail('DEVICE_STATUS_INVALID')
        values['status']=status
    if name is not None: values['name']=text(name,160,True)
    if app_version is not None: values['app_version']=text(app_version,40)
    if metadata_json is not None:
        values['metadata_json']=validate_device_metadata(metadata_json)
    if not values: fail('NO_CHANGES')
    conn.execute(update(devices).where(devices.c.id==device_id).values(**values))
    return {**dict(d),**values}


def authenticate_device(conn, raw_token: str, *, for_update: bool = False):
    if not raw_token: fail('DEVICE_TOKEN_REQUIRED',401)
    query = select(devices).where(devices.c.token_hash==digest(raw_token))
    if for_update:
        query = query.with_for_update()
    d=conn.execute(query).mappings().first()
    if not d or d['status']!='active': fail('DEVICE_TOKEN_INVALID',401)
    metadata = d['metadata_json']
    if not isinstance(metadata, dict) or not active_window({
        'status': 'active', 'valid_from': metadata.get('valid_from'), 'valid_until': metadata.get('valid_until'),
    }):
        fail('DEVICE_SHIFT_INACTIVE', 401)
    return dict(d)


def heartbeat(conn, raw_token: str, body: dict):
    d=authenticate_device(conn,raw_token,for_update=True)
    pending=body.get('pending_count',0)
    if isinstance(pending,bool) or not isinstance(pending,(int,float)) or not math.isfinite(pending) or pending<0 or pending>1_000_000: fail('DEVICE_PENDING_INVALID')
    values={
        'last_seen_at':now(),
        'pending_count':int(pending),
        'app_version':text(body.get('app_version') or d.get('app_version'),40),
    }
    if body.get('synced') is True: values['last_sync_at']=values['last_seen_at']
    meta=body.get('metadata')
    if meta is not None:
        if not isinstance(meta,dict): fail('DEVICE_METADATA_INVALID')
        # A bearer device token can report telemetry, not change its policy.
        # Preserve administrative scope and shift metadata even when the client
        # submits an empty object or forged policy fields.
        telemetry = {}
        for key, maximum in (('browser', 160), ('user_agent', 500)):
            if key in meta:
                telemetry[key] = text(meta[key], maximum)
        if 'kiosk' in meta:
            if not isinstance(meta['kiosk'], bool): fail('DEVICE_KIOSK_BOOLEAN_REQUIRED')
            telemetry['kiosk'] = meta['kiosk']
        values['metadata_json']={**d['metadata_json'], **telemetry}
    conn.execute(update(devices).where(devices.c.id==d['id']).values(**values))
    return {'id':d['id'],'site_id':d['site_id'],'status':'ok',**values}
