from __future__ import annotations

from app.application.ports import persistence
from app.core.security import digest
from app.domain import accounts, now


def identify_request(request, tx, write: bool = False):
    """Resolve the session cookie to an active user; writes also require the CSRF header."""
    token = request.cookies.get('px_session', '')
    session = persistence.identity.session(tx, digest(token)) if token else None
    accounts.require_live_session(session, now())
    user = accounts.require_active_account(persistence.identity.user(tx, session['user_id']))
    if write:
        accounts.require_csrf(request.headers.get('x-csrf', ''), session['csrf'])
    return user, session
