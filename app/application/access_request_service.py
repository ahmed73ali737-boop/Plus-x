"""Legacy site access requests (superseded by account requests, still listed)."""
from __future__ import annotations

from app.application.ports import persistence
from app.domain import NotFound, fail

REQUEST_STATUSES = ('pending', 'approved', 'rejected')


def list_requests(tx, site_id: str):
    return persistence.site_admin.access_requests(tx, site_id)


def set_request_status(tx, site_id: str, request_id: str, status: str):
    if status not in REQUEST_STATUSES:
        fail('REQUEST_STATUS_INVALID')
    request = persistence.site_admin.access_request(tx, site_id, request_id)
    if not request:
        fail('ACCESS_REQUEST_NOT_FOUND', NotFound)
    persistence.site_admin.set_access_request_status(tx, request_id, status)
    return {**request, 'status': status}
