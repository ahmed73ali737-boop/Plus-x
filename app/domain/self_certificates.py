"""Self-declared participation certificates: participant submission rules."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from app.domain.errors import Conflict, Forbidden, InvalidInput, NotFound, Unavailable, fail
from app.domain.guards import require_found
from app.domain.values import text

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


# Request links ---------------------------------------------------------------------------

LINK_REQUIRED_FIELDS = frozenset({'event_id', 'model_id', 'share_text', 'idempotency_key'})
LINK_FIELDS = LINK_REQUIRED_FIELDS | {'expected_revision_id'}
CURRENT_SCHEMA_VERSION = 2
LINK_STATES = ('active', 'paused')


@dataclass(frozen=True)
class LinkRequest:
    """Input of "create an owner-only request link", validated once.

    ``identity()`` is what idempotent replays are compared on: the same key with a different
    event, model, share text or expected revision is a conflict, never a silent second link.
    """

    event_id: str
    model_id: str
    share_text: str
    idempotency_key: str
    expected_revision_id: str | None = None

    @staticmethod
    def check_shape(body) -> None:
        """Strict field set; runs before authentication-dependent work (historical error precedence)."""
        if not isinstance(body, dict) or set(body) - LINK_FIELDS or not LINK_REQUIRED_FIELDS <= set(body):
            fail('LINK_INPUT_INVALID')

    @classmethod
    def parse(cls, body: dict) -> 'LinkRequest':
        cls.check_shape(body)
        event_id, model_id = text(body['event_id'], 64, True), text(body['model_id'], 64, True)
        key, share_text = text(body['idempotency_key'], 80, True), text(body['share_text'], 4000, True)
        expected = text(body['expected_revision_id'], 64, True) if 'expected_revision_id' in body else None
        return cls(event_id, model_id, share_text, key, expected)

    def identity(self) -> dict:
        identity = dict(event_id=self.event_id, model_id=self.model_id, share_text=self.share_text)
        if self.expected_revision_id is not None:
            identity['expected_revision_id'] = self.expected_revision_id
        return identity


def require_same_operation(stored_hash: str, input_hash: str) -> None:
    """Replaying an idempotency key is allowed only with the identical input."""
    if stored_hash != input_hash:
        fail('IDEMPOTENCY_CONFLICT', Conflict)


def require_pilot_available(allowed: bool) -> None:
    """The certificate pilot gate must allow this owner and event."""
    if not allowed:
        fail('CERTIFICATE_PILOT_UNAVAILABLE', Conflict)


def require_expected_revision(expected: str | None, current: str | None) -> None:
    """Optimistic check: the model must still be at the revision the owner looked at."""
    if expected is not None and expected != current:
        fail('MODEL_REVISION_CHANGED', Conflict)


def require_revision_available(revision: dict | None) -> dict:
    return require_found(revision, 'REVISION_UNAVAILABLE', Conflict)


def require_asset_owned(asset: dict | None) -> dict:
    return require_found(asset, 'ASSET_OWNER_MISMATCH', Conflict)


def require_current_schema(revision: dict) -> None:
    """Links are created only from models upgraded to the current design schema."""
    if revision['schema_version'] != CURRENT_SCHEMA_VERSION:
        fail('MODEL_UPGRADE_REQUIRED', Conflict)


def require_row_version(expected, row: dict) -> None:
    """Strict optimistic concurrency: an int equal to the stored row_version (bool/str never match)."""
    if type(expected) is not int or expected != row['row_version']:
        fail('VERSION_CONFLICT', Conflict)


def require_changed(changed: bool) -> None:
    """A guarded update that touched no row lost the race."""
    if not changed:
        fail('VERSION_CONFLICT', Conflict)


@dataclass(frozen=True)
class LinkStateChange:
    status: str
    row_version: int

    @classmethod
    def parse(cls, body, link: dict) -> 'LinkStateChange':
        """Pause/resume a link: exactly {status, row_version}, status active|paused, version still current."""
        if not isinstance(body, dict) or set(body) != {'status', 'row_version'} or body['status'] not in LINK_STATES:
            fail('LINK_STATE_INVALID')
        require_row_version(body['row_version'], link)
        return cls(body['status'], body['row_version'])

    @property
    def resumes(self) -> bool:
        return self.status == 'active'


def require_public_link(row: dict | None, token_matches: bool) -> dict:
    """A public link is revealed only to the exact token; anything else is not found."""
    if not row or not token_matches:
        fail('NOT_FOUND', NotFound)
    return row


# Models and assets -------------------------------------------------------------------------

MODEL_OPERATION_KEY = re.compile(r'[A-Za-z0-9_-]{16,80}')
MAX_PAGE_SIZE = 100
FILTER_LENGTH = 160
ASSET_KINDS = ('background', 'stamp')
MAX_BACKGROUND_BYTES = 3_000_000
MAX_STAMP_BYTES = 999_999
MAX_NORMALIZED_BYTES = 80_000_000


def page_window(offset, limit) -> tuple[int, int]:
    if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= MAX_PAGE_SIZE:
        fail('PAGE_INVALID')
    return offset, limit


def search_filter(q) -> str:
    if not isinstance(q, str) or len(q) > FILTER_LENGTH:
        fail('FILTER_INVALID')
    return q.strip()


def require_asset_reference(asset_id) -> str:
    """Asset ids that cannot exist are concealed rather than reported as malformed."""
    if not isinstance(asset_id, str) or not 1 <= len(asset_id) <= 64:
        fail('NOT_FOUND', NotFound)
    return asset_id


def require_asset_of_kind(asset: dict | None, kind: str | None) -> dict:
    if not asset or (kind and asset['kind'] != kind):
        fail('NOT_FOUND', NotFound)
    return asset


def require_model_operation_key(model_id, key) -> None:
    """A creation idempotency key is only valid for new models and in the bounded alphabet."""
    if model_id is not None or not isinstance(key, str) or not MODEL_OPERATION_KEY.fullmatch(key):
        fail('MODEL_INPUT_INVALID')


def require_upload(data, kind) -> None:
    """Size/kind gate before the isolated process ever sees the bytes."""
    if kind not in ASSET_KINDS:
        fail('ASSET_KIND_INVALID')
    if not isinstance(data, bytes) or not data:
        fail('FILE_EMPTY')
    if len(data) > (MAX_STAMP_BYTES if kind == 'stamp' else MAX_BACKGROUND_BYTES):
        fail('STAMP_TOO_LARGE' if kind == 'stamp' else 'BACKGROUND_TOO_LARGE')


def require_normalized_size(normalized: bytes) -> None:
    if not normalized or len(normalized) > MAX_NORMALIZED_BYTES:
        fail('ASSET_RESOURCE_LIMIT')


def asset_worker_error(code: str) -> None:
    """The worker reports a stable code: isolation problems are unavailability, the rest is bad input."""
    fail(code, Unavailable if code == 'ASSET_PROCESS_ISOLATION_UNAVAILABLE' else InvalidInput)


# Participant browser sessions and acceptance -------------------------------------------------

BROWSER_SEED = re.compile(r'[a-f0-9]{64}')


def require_browser_seed(seed) -> str:
    """A fresh browser session needs the 64-hex storage seed the page generated."""
    if not isinstance(seed, str) or not BROWSER_SEED.fullmatch(seed):
        fail('BROWSER_STORAGE_REQUIRED')
    return seed


def require_browser_token(row: dict | None, token_matches: bool) -> dict:
    """The cookie must belong to a stored browser session."""
    if not row or not token_matches:
        fail('BROWSER_SESSION_INVALID', Forbidden)
    return row


def require_key_version_available(version: str | None) -> str:
    """A browser cookie can be re-issued only under a key version the keyring still holds."""
    if version is None:
        fail('CERTIFICATE_KEY_VERSION_UNAVAILABLE', Unavailable)
    return version


def require_owner_still_authorised(allowed: bool) -> None:
    """The link owner must still hold authority for the event when a participant submits."""
    if not allowed:
        fail('CERTIFICATE_LINK_UNAVAILABLE', Conflict)


def require_issued_certificate(certificate: dict | None) -> dict:
    """An issued request must have its certificate row, otherwise its state cannot be shown."""
    if not certificate:
        fail('CERTIFICATE_STATE_UNAVAILABLE', Unavailable)
    return certificate
