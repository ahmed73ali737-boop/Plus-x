from __future__ import annotations

import hmac

from app.core.security import digest
from app.db import sessions, users
from app.domain import fail, now
from app.infrastructure.repository import fetch_one


def identify_request(request, conn, write: bool = False):
    token = request.cookies.get('px_session', '')
    session = fetch_one(conn, sessions, 'token_hash', digest(token)) if token else None
    if not session or session['expires_at'] <= now():
        fail('LOGIN_REQUIRED', 401)
    user = fetch_one(conn, users, 'id', session['user_id'])
    if not user or not user['active']:
        fail('LOGIN_REQUIRED', 401)
    if write and not hmac.compare_digest(request.headers.get('x-csrf', ''), session['csrf']):
        fail('CSRF_REQUIRED', 403)
    return user, session
