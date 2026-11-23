"""Rules for the optional proof of phone ownership (the code itself is owned by the Channel Gateway)."""
import re

from app.domain.errors import Conflict, Gone, InvalidInput, RateLimited, Unavailable, fail

START_LIMIT_PER_HOUR = 3
PENDING_MINUTES = 10


def require_available(available):
    if not available:
        fail('PHONE_VERIFICATION_UNAVAILABLE', Unavailable)


def require_phone(phone):
    if not phone:
        fail('PHONE_REQUIRED')
    return phone


def require_code(code):
    if not isinstance(code, str) or not re.fullmatch(r'[0-9]{4,8}', code):
        fail('CODE_INVALID')
    return code


def require_start_allowed(starts_last_hour):
    if starts_last_hour >= START_LIMIT_PER_HOUR:
        fail('VERIFICATION_RATE_LIMITED', RateLimited)


def require_pending(pending):
    if not pending:
        fail('NO_PENDING_VERIFICATION', Conflict)
    return pending


def start_outcome(out):
    """Raise the domain error matching a gateway outcome; return the outcome when the code was sent."""
    if out.get('unavailable'):
        fail('PHONE_VERIFICATION_UNAVAILABLE', Unavailable)
    if 'refused' in out:
        if out['refused'] == 429:
            fail('VERIFICATION_RATE_LIMITED', RateLimited)
        fail('PHONE_VERIFICATION_REFUSED', Unavailable)  # the gateway's text and key never reach the client
    return out


def check_outcome(out):
    if out.get('unavailable'):
        fail('PHONE_VERIFICATION_UNAVAILABLE', Unavailable)
    if 'refused' in out:
        status = out['refused']
        if status == 410:
            fail('VERIFICATION_EXPIRED', Gone)
        if status == 429:
            fail('VERIFICATION_ATTEMPTS_EXHAUSTED', RateLimited)
        if status in (404, 409):
            fail('NO_PENDING_VERIFICATION', Conflict)
        fail('PHONE_VERIFICATION_REFUSED', Unavailable)
    if not out['valid']:
        fail('INVALID_CODE', InvalidInput)
