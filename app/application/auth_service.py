from __future__ import annotations

import hmac

from app.application.ports import persistence
from app.core.security import digest
from app.domain import Forbidden, Unauthenticated, fail, now


def identify_request(request, tx, write: bool = False):
    """Resolve the session cookie to an active user; writes also require the CSRF header."""
    token = request.cookies.get('px_session', '')
    session = persistence.identity.session(tx, digest(token)) if token else None
    if not session or session['expires_at'] <= now():
        fail('LOGIN_REQUIRED', Unauthenticated)
    user = persistence.identity.user(tx, session['user_id'])
    if not user or not user['active']:
        fail('LOGIN_REQUIRED', Unauthenticated)
    if write and not hmac.compare_digest(request.headers.get('x-csrf', ''), session['csrf']):
        fail('CSRF_REQUIRED', Forbidden)
    return user, session
