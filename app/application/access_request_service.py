"""Legacy site access requests (superseded by account requests, still listed)."""
from __future__ import annotations

from app.application.ports import persistence
from app.domain.sites import require_access_request, require_access_request_status


def list_requests(tx, site_id: str):
    return persistence.site_admin.access_requests(tx, site_id)


def set_request_status(tx, site_id: str, request_id: str, status: str):
    require_access_request_status(status)
    request = require_access_request(persistence.site_admin.access_request(tx, site_id, request_id))
    persistence.site_admin.set_access_request_status(tx, request_id, status)
    return {**request, 'status': status}
