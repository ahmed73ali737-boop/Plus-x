"""Persisted user preferences and explicit, platform-admin account notifications."""
from fastapi import Request
from sqlalchemy import select, insert, update
from app.db import preferences, notifications, users
from app.domain import fail, text, now
from app.application.audit_service import new_id, write_audit

DEFAULTS = {'theme': 'system', 'text_size': 'normal', 'reduce_motion': False,
            'notifications_enabled': True}


def install_account_routes(app, engine, *, identify):
    @app.get('/api/account/preferences')
    def get_preferences(request: Request):
        with engine.connect() as c:
            user, _ = identify(request, c)
            config = c.execute(select(preferences.c.config).where(preferences.c.user_id == user['id'])).scalar_one_or_none()
            return {**DEFAULTS, **(config or {})}

    @app.put('/api/account/preferences')
    def save_preferences(body: dict, request: Request):
        if set(body) != set(DEFAULTS) or body.get('theme') not in ('system', 'light', 'dark') or body.get('text_size') not in ('normal', 'large'):
            fail('PREFERENCES_INVALID')
        if any(type(body.get(key)) is not bool for key in ('reduce_motion', 'notifications_enabled')):
            fail('PREFERENCES_INVALID')
        with engine.begin() as c:
            user, _ = identify(request, c, True)
            exists = c.execute(select(preferences.c.user_id).where(preferences.c.user_id == user['id'])).first()
            if exists:
                c.execute(update(preferences).where(preferences.c.user_id == user['id']).values(config=body))
            else:
                c.execute(insert(preferences).values(user_id=user['id'], config=body))
        return body

    @app.get('/api/account/notifications')
    def inbox(request: Request):
        with engine.connect() as c:
            user, _ = identify(request, c)
            items = c.execute(select(notifications.c.id, notifications.c.title, notifications.c.body,
                                     notifications.c.created_at, notifications.c.read_at)
                              .where(notifications.c.user_id == user['id'])
                              .order_by(notifications.c.created_at.desc(), notifications.c.id).limit(100)).mappings().all()
            return {'items': [dict(item) for item in items], 'channel': 'in_app'}

    @app.post('/api/account/notifications/{notification_id}/read')
    def mark_read(notification_id: str, request: Request):
        with engine.begin() as c:
            user, _ = identify(request, c, True)
            result = c.execute(update(notifications).where(notifications.c.id == notification_id,
                notifications.c.user_id == user['id']).values(read_at=now()))
            if not result.rowcount:
                fail('NOT_FOUND', 404)
        return {'ok': True}

    @app.post('/api/admin/notifications')
    def send_notification(body: dict, request: Request):
        with engine.begin() as c:
            user, _ = identify(request, c, True)
            if user['role'] != 'platform':
                fail('FORBIDDEN_ROLE', 403)
            email = text(body.get('email'), 200, True).lower()
            target = c.execute(select(users).where(users.c.email == email, users.c.active == 1)).mappings().first()
            if not target:
                fail('ACCOUNT_NOT_FOUND', 404)
            nid = new_id()
            c.execute(insert(notifications).values(id=nid, user_id=target['id'], sender_id=user['id'],
                title=text(body.get('title'), 160, True), body=text(body.get('body'), 2000, True), created_at=now()))
            write_audit(c, user, user['scope_id'], 'notification_sent', {'notification_id': nid, 'recipient_id': target['id']})
            return {'id': nid, 'status': 'delivered_to_inbox', 'channel': 'in_app'}
