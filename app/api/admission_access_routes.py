"""HTTP adapter: scoped admission capabilities and time-bounded committee assignments."""
from fastapi import Request

from app.api.errors import install_error_handlers
from app.application import committee_service
from app.application.access import event_permissions, require_event_permission


def install_admission_access_routes(app, engine, identify):
    install_error_handlers(app)

    @app.get('/api/admin/admission/events')
    def admission_events(request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return {'events': committee_service.admission_events(tx, user)}

    @app.get('/api/admin/events/{event_id}/permissions')
    def admission_permissions(event_id: str, request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            require_event_permission(tx, user, event_id, 'guests.read')
            return {'event_id': event_id, 'permissions': sorted(event_permissions(tx, user, event_id))}

    @app.get('/api/admin/events/{event_id}/committee')
    def committee_list(event_id: str, request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return committee_service.committee(tx, user, event_id)

    @app.post('/api/admin/events/{event_id}/committee')
    def committee_assign(event_id: str, body: dict, request: Request):
        with engine.begin() as tx:
            actor, _ = identify(request, tx, True)
            return committee_service.request_assignment(tx, actor, event_id, body)

    @app.patch('/api/admin/events/{event_id}/committee/{assignment_id}')
    def committee_update(event_id: str, assignment_id: str, body: dict, request: Request):
        with engine.begin() as tx:
            actor, _ = identify(request, tx, True)
            return committee_service.update_assignment(tx, actor, event_id, assignment_id, body)
