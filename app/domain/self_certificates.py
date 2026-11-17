"""Self-declared participation certificates: participant submission rules."""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.errors import fail

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
