"""Event committee (scoped admission staff) use cases."""
from __future__ import annotations

from app.application import account_requests as account_request_service
from app.application.access import event_permissions, require_event_permission
from app.application.audit_service import write_audit
from app.application.ports import persistence
from app.domain.authorization import EVENT_ROLE_PERMISSIONS
from app.domain.committee import (
    assignment_changes,
    assignment_view,
    require_assignee,
    require_assignment,
    require_committee_role,
)


def admission_events(tx, user) -> list[dict]:
    """Events where the user holds at least one admission capability."""
    events = []
    for event in persistence.sites.list_all(tx):
        if event['kind'] != 'event':
            continue
        permissions = event_permissions(tx, user, event['id'])
        if permissions:
            events.append({'id': event['id'], 'slug': event['slug'],
                           'title': event['draft'].get('title', event['slug']), 'permissions': sorted(permissions)})
    return events


def committee(tx, user, event_id: str) -> dict:
    require_event_permission(tx, user, event_id, 'committee.manage')
    rows = persistence.committee.members(tx, event_id, tuple(EVENT_ROLE_PERMISSIONS))
    return {'assignments': [assignment_view(row) for row in rows], 'roles': sorted(EVENT_ROLE_PERMISSIONS)}


def request_assignment(tx, actor, event_id: str, body: dict) -> dict:
    """Committee membership is always a reviewed account request, never a direct grant."""
    require_event_permission(tx, actor, event_id, 'committee.manage')
    require_committee_role(body.get('role'), EVENT_ROLE_PERMISSIONS)
    target = persistence.identity.user(tx, body.get('user_id')) if body.get('user_id') else None
    require_assignee(body.get('user_id'), target)
    payload = dict(body)
    if target:
        payload.update(name=target['name'], email=target['email'] if not target['email'].startswith('tel:') else None,
                       phone=persistence.identity.phone_of(tx, target['id']))
    return account_request_service.submit(tx, actor=actor, body=payload, purpose='committee', scope_type='site',
                                          scope_id=event_id, role='member', assignment_role=body['role'])


def update_assignment(tx, actor, event_id: str, assignment_id: str, body: dict) -> dict:
    require_event_permission(tx, actor, event_id, 'committee.manage')
    current = require_assignment(persistence.committee.assignment(tx, assignment_id, event_id, tuple(EVENT_ROLE_PERMISSIONS)))
    values = assignment_changes(current, body)
    persistence.committee.update_assignment(tx, assignment_id, values)
    write_audit(tx, actor, event_id, 'committee_updated', {'assignment_id': assignment_id, **values})
    return {**assignment_view(current), **values}
