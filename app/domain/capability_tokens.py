"""Shape and freshness rules of the signed capability tokens used by self-service certificates.

A token is ``<key version>.<identifier>.<signature>``; a browser request nonce is
``<key version>.<15-minute epoch>.<signature>``. Computing HMACs and reading keys are adapters
(``self_certificate_crypto``); what counts as a well-formed, current and verified capability is decided here.
Every failure of a *public* token is "not found": a probe learns nothing about which part was wrong.
"""
from __future__ import annotations

import re

from app.domain.errors import Forbidden, NotFound, Unavailable, fail

PART = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
MAX_TOKEN_LENGTH = 220
MAX_NONCE_LENGTH = 180
NONCE_WINDOW_SECONDS = 900
NONCE_EPOCH_TOLERANCE = 1


def require_identifier(ident) -> str:
    """Only plain identifiers can be signed into a token."""
    if not isinstance(ident, str) or not PART.fullmatch(ident):
        fail('TOKEN_INVALID', NotFound)
    return ident


def parse_token(token) -> tuple[str, str, str]:
    """(version, identifier, signature) of a well-formed token; anything else does not exist."""
    if not isinstance(token, str) or len(token) > MAX_TOKEN_LENGTH:
        fail('NOT_FOUND', NotFound)
    parts = token.split('.')
    if len(parts) != 3 or not all(PART.fullmatch(part) for part in parts):
        fail('NOT_FOUND', NotFound)
    return parts[0], parts[1], parts[2]


def require_known_key_version(known: bool) -> None:
    """A retired or unknown key version cannot be verified: the service is unavailable, not the token wrong."""
    if not known:
        fail('CERTIFICATE_KEY_VERSION_UNAVAILABLE', Unavailable)


def require_valid_signature(valid: bool) -> None:
    if not valid:
        fail('NOT_FOUND', NotFound)


def parse_nonce(nonce) -> tuple[str, str, str]:
    if not isinstance(nonce, str) or len(nonce) > MAX_NONCE_LENGTH:
        fail('REQUEST_NONCE_INVALID', Forbidden)
    parts = nonce.split('.')
    if len(parts) != 3:
        fail('REQUEST_NONCE_INVALID', Forbidden)
    return parts[0], parts[1], parts[2]


def current_epoch(now_seconds: float) -> int:
    return int(now_seconds) // NONCE_WINDOW_SECONDS


def require_fresh_epoch(epoch: str, now_seconds: float) -> None:
    """Accepted for the current 15-minute window and one window either side (clock skew, slow forms)."""
    if not epoch.isdigit() or abs(current_epoch(now_seconds) - int(epoch)) > NONCE_EPOCH_TOLERANCE:
        fail('REQUEST_NONCE_EXPIRED', Forbidden)


def require_valid_nonce(key_known: bool, signature_valid: bool) -> None:
    if not key_known or not signature_valid:
        fail('REQUEST_NONCE_INVALID', Forbidden)
