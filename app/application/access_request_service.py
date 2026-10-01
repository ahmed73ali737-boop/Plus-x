from __future__ import annotations

from sqlalchemy import select, update

from app.db import requests
from app.domain import fail

REQUEST_STATUSES=('pending','approved','rejected')


def list_requests(conn, site_id: str):
    return [dict(x) for x in conn.execute(select(requests).where(requests.c.site_id==site_id).order_by(requests.c.created_at.desc())).mappings()]


def set_request_status(conn, site_id: str, request_id: str, status: str):
    if status not in REQUEST_STATUSES: fail('REQUEST_STATUS_INVALID')
    req=conn.execute(select(requests).where(requests.c.id==request_id,requests.c.site_id==site_id)).mappings().first()
    if not req: fail('ACCESS_REQUEST_NOT_FOUND',404)
    conn.execute(update(requests).where(requests.c.id==request_id).values(status=status))
    return {**dict(req),'status':status}
