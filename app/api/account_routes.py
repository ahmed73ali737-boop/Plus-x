"""Persisted user preferences and explicit, platform-admin account notifications."""
from fastapi import Request

from app.api.errors import install_error_handlers
from app.application import account_service as accounts
from app.domain.accounts import PREFERENCE_DEFAULTS, check_preferences

DEFAULTS = PREFERENCE_DEFAULTS


def install_account_routes(app, engine, *, identify):
    install_error_handlers(app)

    @app.get('/api/account/preferences')
    def get_preferences(request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return accounts.preferences(tx, user)

    @app.put('/api/account/preferences')
    def save_preferences(body: dict, request: Request):
        check_preferences(body)
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return accounts.save_preferences(tx, user, body)

    @app.get('/api/account/notifications')
    def inbox(request: Request):
        with engine.connect() as tx:
            user, _ = identify(request, tx)
            return accounts.inbox(tx, user)

    @app.post('/api/account/notifications/{notification_id}/read')
    def mark_read(notification_id: str, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            accounts.mark_read(tx, user, notification_id)
        return {'ok': True}

    @app.post('/api/admin/notifications')
    def send_notification(body: dict, request: Request):
        with engine.begin() as tx:
            user, _ = identify(request, tx, True)
            return accounts.send_notification(tx, user, body)
