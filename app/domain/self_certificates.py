"""Self-declared participation certificates: participant submission rules."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from app.domain.errors import Conflict, Forbidden, NotFound, Unavailable, fail

SUBMISSION_FIELDS = frozenset({'name', 'phone', 'consent', 'request_nonce'})
NAME_LENGTH = (1, 250)
PHONE_LENGTH = (1, 60)
NONCE_LENGTH = (20, 200)


@dataclass(frozen=True)
class ParticipantSubmission:
    name: str
    phone: str
    consent: bool
    request_nonce: str


def _bounded(value, bounds, nonblank) -> bool:
    low, high = bounds
    return isinstance(value, str) and low <= len(value) <= high and (not nonblank or bool(value.strip()))


def participant_submission(body) -> ParticipantSubmission:
    """Strict self-declaration input; guards run before any request/job insertion.

    Errors never echo personal data: every malformed input is PARTICIPANT_INPUT_INVALID,
    except a missing/negative consent, which is CONSENT_REQUIRED.
    """
    if not isinstance(body, dict):
        fail('PARTICIPANT_INPUT_INVALID')
    if body.get('consent') is not True:
        fail('CONSENT_REQUIRED')
    if set(body) != SUBMISSION_FIELDS:
        fail('PARTICIPANT_INPUT_INVALID')
    if not (_bounded(body['name'], NAME_LENGTH, True) and _bounded(body['phone'], PHONE_LENGTH, True)
            and _bounded(body['request_nonce'], NONCE_LENGTH, False)):
        fail('PARTICIPANT_INPUT_INVALID')
    return ParticipantSubmission(body['name'], body['phone'], True, body['request_nonce'])


CONSENT_TEXT = ('أقر بأنني شاركت في هذه الفعالية وأوافق على تزويد الجهة المنظمة باسمي ورقم هاتفي '
                'لإصدار الشهادة وإدارة سجلها.')
CONSENT_VERSION = 'self-declaration-ar-v1'
DECLARED_PHONE = re.compile(r'\+?[0-9]{7,20}')


def declared_phone(value: str) -> str:
    """Digits (any script) with optional leading +; spaces, dashes and brackets are dropped."""
    value = ''.join(str(unicodedata.decimal(char)) if char.isdecimal() else char for char in value)
    value = re.sub(r'[ ()\-]', '', value)
    if not DECLARED_PHONE.fullmatch(value):
        fail('PHONE_INVALID')
    return value


def browser_remaining_seconds(created_at: str, remember_seconds: int, at: datetime) -> int:
    """Seconds left on the browser's remember window; a malformed or naive timestamp is invalid."""
    try:
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None:
            raise ValueError()
        return int(created.timestamp() + remember_seconds - at.timestamp())
    except (ValueError, TypeError):
        fail('BROWSER_SESSION_INVALID', Forbidden)


def require_browser_not_expired(remaining_seconds: int) -> None:
    if remaining_seconds <= 0:
        fail('BROWSER_SESSION_EXPIRED', Forbidden)


def require_accepting(accept_enabled: bool, link: dict) -> None:
    """New participant requests need the operator switch on and an active link."""
    if not accept_enabled:
        fail('CERTIFICATE_REQUESTS_PAUSED', Conflict)
    if link['status'] != 'active':
        fail('CERTIFICATE_LINK_PAUSED', Conflict)


def require_revision_intact(stored_hash: str, computed_hash: str) -> None:
    if computed_hash != stored_hash:
        fail('REVISION_INTEGRITY_ERROR', Unavailable)


def require_failed_request(request: dict | None) -> dict:
    """Retry starts from an owned request that failed."""
    if not request:
        fail('NOT_FOUND', NotFound)
    if request['status'] != 'failed':
        fail('REQUEST_NOT_FAILED', Conflict)
    return request


def require_failed_job(job: dict) -> None:
    """...and whose generation job failed too (a running or pending job is never requeued)."""
    if job['status'] != 'failed':
        fail('REQUEST_NOT_FAILED', Conflict)
