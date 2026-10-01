from __future__ import annotations

from sqlalchemy import insert, select, update

from app.core.security import digest
from app.domain import fail, now, text
from app.db import devices
from app.application.audit_service import new_id

DEVICE_TYPES = ('kiosk','tablet','display','operator')
DEVICE_STATUSES = ('active','disabled','retired')


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
        metadata_json=metadata_json if isinstance(metadata_json,dict) else {},
        created_at=now(),
    ))
    return did


def list_devices(conn, site_id: str):
    rows=conn.execute(select(devices).where(devices.c.site_id==site_id).order_by(devices.c.created_at.desc())).mappings()
    return [{k:v for k,v in dict(x).items() if k!='token_hash'} for x in rows]


def update_device(conn, device_id: str, *, status=None, name=None, app_version=None, metadata_json=None):
    d=conn.execute(select(devices).where(devices.c.id==device_id)).mappings().first()
    if not d: fail('DEVICE_NOT_FOUND',404)
    values={}
    if status is not None:
        if status not in DEVICE_STATUSES: fail('DEVICE_STATUS_INVALID')
        values['status']=status
    if name is not None: values['name']=text(name,160,True)
    if app_version is not None: values['app_version']=text(app_version,40)
    if metadata_json is not None:
        if not isinstance(metadata_json,dict): fail('DEVICE_METADATA_INVALID')
        values['metadata_json']=metadata_json
    if not values: fail('NO_CHANGES')
    conn.execute(update(devices).where(devices.c.id==device_id).values(**values))
    return {**dict(d),**values}


def authenticate_device(conn, raw_token: str):
    if not raw_token: fail('DEVICE_TOKEN_REQUIRED',401)
    d=conn.execute(select(devices).where(devices.c.token_hash==digest(raw_token))).mappings().first()
    if not d or d['status']!='active': fail('DEVICE_TOKEN_INVALID',401)
    return dict(d)


def heartbeat(conn, raw_token: str, body: dict):
    d=authenticate_device(conn,raw_token)
    pending=body.get('pending_count',0)
    if isinstance(pending,bool) or not isinstance(pending,(int,float)) or pending<0 or pending>1_000_000: fail('DEVICE_PENDING_INVALID')
    values={
        'last_seen_at':now(),
        'pending_count':int(pending),
        'app_version':text(body.get('app_version') or d.get('app_version'),40),
    }
    if body.get('synced') is True: values['last_sync_at']=values['last_seen_at']
    meta=body.get('metadata')
    if meta is not None:
        if not isinstance(meta,dict): fail('DEVICE_METADATA_INVALID')
        values['metadata_json']=meta
    conn.execute(update(devices).where(devices.c.id==d['id']).values(**values))
    return {'id':d['id'],'site_id':d['site_id'],'status':'ok',**values}
